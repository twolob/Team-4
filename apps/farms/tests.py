import os
import shutil
import tempfile
import uuid
import warnings
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from PIL import Image

from apps.accounts.models import User
from apps.farmers.models import FarmerProfile
from apps.farms.models import (
    CropSeason,
    ExpenseRecord,
    Farm,
    FarmActivity,
    HarvestBatch,
    InputRecord,
    Plot,
    PrivateInspectionStorage,
    QualityInspection,
    validate_inspection_photo,
)


class FarmModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Test Farmer")

    def test_farm_uses_uuid_primary_key_and_relationship(self):
        farm = Farm.objects.create(
            farmer=self.farmer,
            name="North Orchard",
        )
        self.assertTrue(farm.pk)
        self.assertEqual(farm.farmer, self.farmer)

    def test_farm_coordinates_must_be_supplied_together(self):
        with self.assertRaises(ValidationError):
            Farm.objects.create(
                farmer=self.farmer,
                name="Broken Coordinates",
                latitude="1.234567",
            )

    def test_farm_latitude_and_longitude_ranges_are_valid(self):
        with self.assertRaises(ValidationError):
            Farm.objects.create(
                farmer=self.farmer,
                name="Bad Latitude",
                latitude=91,
                longitude=12.5,
            )

        with self.assertRaises(ValidationError):
            Farm.objects.create(
                farmer=self.farmer,
                name="Bad Longitude",
                latitude=1.0,
                longitude=181,
            )

    def test_farm_area_must_be_positive_when_supplied(self):
        with self.assertRaises(ValidationError):
            Farm.objects.create(
                farmer=self.farmer,
                name="Negative Area",
                total_area_hectares=0,
            )


class PlotModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Plot Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Main Farm")

    def test_plot_has_unique_code_per_farm(self):
        Plot.objects.create(farm=self.farm, name="A1", plot_code="P-001")

        with self.assertRaises(ValidationError):
            Plot.objects.create(farm=self.farm, name="A2", plot_code="P-001")

    def test_plot_codes_are_not_global_unique(self):
        Plot.objects.create(farm=self.farm, name="A1", plot_code="P-001")
        second_farm = Farm.objects.create(farmer=self.farmer, name="Second Farm")
        Plot.objects.create(farm=second_farm, name="B1", plot_code="P-001")

    def test_two_farms_for_same_farmer_can_share_a_name(self):
        Farm.objects.create(farmer=self.farmer, name="Shared Name")
        Farm.objects.create(farmer=self.farmer, name="Shared Name")

    def test_plot_coordinates_and_area_validation(self):
        with self.assertRaises(ValidationError):
            Plot.objects.create(
                farm=self.farm,
                name="Bad Coordinates",
                plot_code="P-002",
                latitude=-12.345678,
            )

        with self.assertRaises(ValidationError):
            Plot.objects.create(
                farm=self.farm,
                name="Bad Area",
                plot_code="P-003",
                area_hectares=0,
            )


class CropSeasonModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Season Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Season Farm")
        self.plot = Plot.objects.create(
            farm=self.farm,
            name="Season Plot",
            plot_code="S-001",
        )

    def test_crop_season_harvest_dates_cannot_precede_planned_planting_date(self):
        with self.assertRaises(ValidationError):
            CropSeason.objects.create(
                plot=self.plot,
                season_name="First Season",
                crop_type="Maize",
                planned_planting_date=date(2024, 1, 10),
                expected_harvest_date=date(2024, 1, 5),
            )

    def test_actual_planting_date_is_optional(self):
        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="No Actual Planting",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 10),
            expected_harvest_date=date(2024, 6, 1),
        )

        self.assertIsNone(season.actual_planting_date)

    def test_actual_harvest_date_cannot_precede_actual_planting_date(self):
        with self.assertRaises(ValidationError):
            CropSeason(
                plot=self.plot,
                season_name="Bad Actual Dates",
                crop_type="Beans",
                planned_planting_date=date(2024, 1, 1),
                actual_planting_date=date(2024, 2, 10),
                expected_harvest_date=date(2024, 6, 1),
                actual_harvest_date=date(2024, 2, 5),
            ).full_clean()

    def test_planned_dates_remain_when_actual_dates_are_recorded(self):
        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Configured Season",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 5),
            actual_planting_date=date(2024, 1, 9),
            expected_harvest_date=date(2024, 7, 1),
            actual_harvest_date=date(2024, 7, 10),
        )

        self.assertEqual(season.planned_planting_date, date(2024, 1, 5))
        self.assertEqual(season.actual_planting_date, date(2024, 1, 9))
        self.assertEqual(season.expected_harvest_date, date(2024, 7, 1))
        self.assertEqual(season.actual_harvest_date, date(2024, 7, 10))

    def test_season_starting_the_day_after_previous_effective_end_is_allowed(self):
        CropSeason.objects.create(
            plot=self.plot,
            season_name="First",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 3, 31),
        )

        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Second",
            crop_type="Beans",
            planned_planting_date=date(2024, 4, 1),
            expected_harvest_date=date(2024, 5, 10),
        )

        self.assertEqual(season.season_name, "Second")

    def test_actual_planting_date_controls_effective_overlap_start(self):
        first = CropSeason.objects.create(
            plot=self.plot,
            season_name="First",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            actual_planting_date=date(2024, 1, 10),
            expected_harvest_date=date(2024, 3, 31),
            actual_harvest_date=date(2024, 3, 15),
        )

        second = CropSeason(
            plot=self.plot,
            season_name="Second",
            crop_type="Beans",
            planned_planting_date=date(2024, 3, 1),
            expected_harvest_date=date(2024, 5, 10),
        )

        self.assertTrue(first._has_overlap_with(second))

    def test_actual_harvest_date_overrides_later_expected_harvest_date(self):
        first = CropSeason.objects.create(
            plot=self.plot,
            season_name="First",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 7, 1),
            actual_harvest_date=date(2024, 3, 15),
        )

        second = CropSeason(
            plot=self.plot,
            season_name="Second",
            crop_type="Beans",
            planned_planting_date=date(2024, 3, 16),
            expected_harvest_date=date(2024, 6, 30),
        )

        self.assertFalse(first._has_overlap_with(second))

    def test_non_cancelled_seasons_overlap(self):
        CropSeason.objects.create(
            plot=self.plot,
            season_name="First",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 3, 31),
        )

        with self.assertRaises(ValidationError):
            CropSeason.objects.create(
                plot=self.plot,
                season_name="Second",
                crop_type="Beans",
                planned_planting_date=date(2024, 3, 31),
                expected_harvest_date=date(2024, 5, 10),
            )

    def test_update_existing_season_into_overlapping_range_is_rejected(self):
        CropSeason.objects.create(
            plot=self.plot,
            season_name="Existing",
            crop_type="Rice",
            planned_planting_date=date(2024, 2, 1),
            expected_harvest_date=date(2024, 3, 10),
        )

        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Editable",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 1, 31),
        )

        season.planned_planting_date = date(2024, 1, 20)
        season.expected_harvest_date = date(2024, 3, 1)

        with self.assertRaises(ValidationError):
            season.save()

    def test_cancelled_season_does_not_block_subsequent_seasons(self):
        CropSeason.objects.create(
            plot=self.plot,
            season_name="Cancelled",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 2, 15),
            status=CropSeason.STATUS_CANCELLED,
        )

        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Next Season",
            crop_type="Rice",
            planned_planting_date=date(2024, 2, 15),
            expected_harvest_date=date(2024, 4, 12),
        )

        self.assertEqual(season.status, CropSeason.STATUS_PLANNED)

    def test_overlap_validation_excludes_current_instance_on_update(self):
        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Editable",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 2, 10),
        )

        season.season_name = "Updated Season"
        season.save()

        self.assertEqual(season.season_name, "Updated Season")

    def test_open_ended_season_blocks_later_seasons(self):
        CropSeason.objects.create(
            plot=self.plot,
            season_name="Open Season",
            crop_type="Cassava",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=None,
        )

        with self.assertRaises(ValidationError):
            CropSeason.objects.create(
                plot=self.plot,
                season_name="Later",
                crop_type="Maize",
                planned_planting_date=date(2024, 2, 1),
            )

    def test_open_ended_season_blocks_later_overlapping_seasons(self):
        CropSeason.objects.create(
            plot=self.plot,
            season_name="Open Season",
            crop_type="Cassava",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=None,
        )

        with self.assertRaises(ValidationError):
            CropSeason.objects.create(
                plot=self.plot,
                season_name="Later Open Season",
                crop_type="Maize",
                planned_planting_date=date(2024, 2, 1),
                expected_harvest_date=None,
            )

    def test_season_move_between_plots_revalidates_target_plot(self):
        second_plot = Plot.objects.create(
            farm=self.farm,
            name="Second Plot",
            plot_code="S-002",
        )
        existing = CropSeason.objects.create(
            plot=second_plot,
            season_name="Existing Second Plot Season",
            crop_type="Wheat",
            planned_planting_date=date(2024, 7, 1),
            expected_harvest_date=date(2024, 8, 15),
        )

        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Move Me",
            crop_type="Maize",
            planned_planting_date=date(2024, 7, 5),
            expected_harvest_date=date(2024, 8, 20),
        )

        season.plot = second_plot
        with self.assertRaises(ValidationError):
            season.save()

        self.assertEqual(CropSeason.objects.get(pk=season.pk).plot, self.plot)
        self.assertEqual(existing.plot, second_plot)

    def test_save_locks_related_plot_row_before_validation(self):
        season = CropSeason(
            plot=self.plot,
            season_name="Locking Season",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 2, 15),
        )

        class LockingQuerySet:
            def __init__(self):
                self.evaluated = False

            def select_for_update(self):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def __iter__(self):
                self.evaluated = True
                return iter([])

        queryset = LockingQuerySet()

        with mock.patch(
            "apps.farms.models.Plot.objects.filter", return_value=queryset
        ) as mock_filter:
            with mock.patch.object(CropSeason, "full_clean") as mock_full_clean:
                season.save()

        mock_filter.assert_called_once()
        self.assertTrue(queryset.evaluated)
        mock_full_clean.assert_called_once_with()

    def test_save_locks_old_and_new_plot_rows_when_season_changes_plots(self):
        second_plot = Plot.objects.create(
            farm=self.farm,
            name="Destination Plot",
            plot_code="S-002",
        )
        season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Move Me",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 1),
            expected_harvest_date=date(2024, 2, 20),
        )
        season.plot = second_plot

        captured = {}

        class LockingQuerySet:
            def __init__(self, ids):
                self.ids = list(ids)

            def select_for_update(self):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def __iter__(self):
                return iter(self.ids)

        def fake_filter(**kwargs):
            captured["pk__in"] = sorted(kwargs["pk__in"])
            return LockingQuerySet(kwargs["pk__in"])

        with mock.patch(
            "apps.farms.models.Plot.objects.filter", side_effect=fake_filter
        ) as mock_filter:
            season.save()

        mock_filter.assert_called_once()
        self.assertEqual(captured["pk__in"], sorted([self.plot.pk, second_plot.pk]))


class FarmActivityModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Activity Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Activity Farm")
        self.plot = Plot.objects.create(
            farm=self.farm,
            name="Activity Plot",
            plot_code="A-001",
        )
        self.season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Planting Season",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 10),
            expected_harvest_date=date(2024, 6, 1),
        )

    def test_valid_activity_creation(self):
        activity = FarmActivity.objects.create(
            crop_season=self.season,
            activity_type="Irrigation",
            activity_date=date(2024, 2, 14),
            description="Applied irrigation during dry spell.",
        )

        self.assertIsNotNone(activity.pk)
        self.assertEqual(activity.activity_type, "Irrigation")

    def test_activity_type_is_required(self):
        with self.assertRaises(ValidationError):
            FarmActivity(
                crop_season=self.season,
                activity_type="   ",
                activity_date=date(2024, 2, 14),
                description="Needs a non-blank type.",
            ).full_clean()

    def test_database_rejects_whitespace_only_activity_type(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FarmActivity.objects.bulk_create(
                    [
                        FarmActivity(
                            crop_season=self.season,
                            activity_type="   ",
                            activity_date=date(2024, 2, 14),
                            description="Whitespace-only activity type.",
                        )
                    ]
                )

    def test_future_activity_date_is_rejected(self):
        future_date = date.today() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            FarmActivity(
                crop_season=self.season,
                activity_type="Inspection",
                activity_date=future_date,
                description="Future activity should not be allowed.",
            ).full_clean()

    def test_recorded_by_is_optional(self):
        activity = FarmActivity(
            crop_season=self.season,
            activity_type="Weeding",
            activity_date=date(2024, 2, 20),
            description="Manual weeding on the plot.",
        )

        activity.full_clean()
        self.assertIsNone(activity.recorded_by)

    def test_recorded_by_is_set_to_null_when_user_deleted(self):
        user = User.objects.create_user(
            email="activity@farmproof.test", password="secret"
        )
        activity = FarmActivity.objects.create(
            crop_season=self.season,
            activity_type="Spraying",
            activity_date=date(2024, 2, 18),
            description="Sprayed pest treatment.",
            recorded_by=user,
        )

        user.delete()
        activity.refresh_from_db()

        self.assertIsNone(activity.recorded_by)

    def test_crop_season_protects_related_activity_records(self):
        FarmActivity.objects.create(
            crop_season=self.season,
            activity_type="Fertilizer",
            activity_date=date(2024, 2, 15),
            description="Applied fertilizer.",
        )

        with self.assertRaises(ProtectedError):
            self.season.delete()

    def test_activity_before_planting_is_allowed(self):
        activity = FarmActivity(
            crop_season=self.season,
            activity_type="Land Preparation",
            activity_date=date(2024, 1, 5),
            description="Prepared the field before planting.",
        )

        activity.full_clean()
        self.assertEqual(activity.activity_date, date(2024, 1, 5))

    def test_activity_after_harvest_is_allowed(self):
        activity = FarmActivity(
            crop_season=self.season,
            activity_type="Cleanup",
            activity_date=date(2024, 6, 15),
            description="Cleaned the field after harvest.",
        )

        activity.full_clean()
        self.assertEqual(activity.activity_date, date(2024, 6, 15))


class InputRecordModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Input Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Input Farm")
        self.plot = Plot.objects.create(
            farm=self.farm,
            name="Input Plot",
            plot_code="I-001",
        )
        self.season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Input Season",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 10),
            actual_planting_date=date(2024, 1, 12),
            expected_harvest_date=date(2024, 6, 1),
            actual_harvest_date=date(2024, 6, 5),
        )

    def test_valid_input_record_creation(self):
        record = InputRecord.objects.create(
            crop_season=self.season,
            input_type="Fertilizer",
            quantity=Decimal("12.5000"),
            unit="kg",
            application_date=date(2024, 2, 14),
            applied_by="A. Farmer",
            notes="Applied top dressing.",
        )

        self.assertIsNotNone(record.pk)
        self.assertEqual(record.input_type, "Fertilizer")

    def test_required_input_type_and_unit(self):
        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="",
                quantity=Decimal("10"),
                unit="kg",
                application_date=date(2024, 2, 14),
            ).full_clean()

        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="Fertilizer",
                quantity=Decimal("10"),
                unit="",
                application_date=date(2024, 2, 14),
            ).full_clean()

    def test_whitespace_only_input_type_and_unit_are_rejected(self):
        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="   ",
                quantity=Decimal("10"),
                unit="kg",
                application_date=date(2024, 2, 14),
            ).full_clean()

        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="Fertilizer",
                quantity=Decimal("10"),
                unit="   ",
                application_date=date(2024, 2, 14),
            ).full_clean()

    def test_zero_and_negative_quantities_are_rejected(self):
        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="Fertilizer",
                quantity=Decimal("0"),
                unit="kg",
                application_date=date(2024, 2, 14),
            ).full_clean()

        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="Fertilizer",
                quantity=Decimal("-1"),
                unit="kg",
                application_date=date(2024, 2, 14),
            ).full_clean()

    def test_future_application_date_is_rejected(self):
        future_date = date.today() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            InputRecord(
                crop_season=self.season,
                input_type="Pesticide",
                quantity=Decimal("2"),
                unit="L",
                application_date=future_date,
            ).full_clean()

    def test_recorded_by_is_optional(self):
        record = InputRecord(
            crop_season=self.season,
            input_type="Herbicide",
            quantity=Decimal("4"),
            unit="L",
            application_date=date(2024, 2, 20),
        )

        record.full_clean()
        self.assertIsNone(record.recorded_by)

    def test_recorded_by_is_set_to_null_when_user_deleted(self):
        user = User.objects.create_user(email="input@farmproof.test", password="secret")
        record = InputRecord.objects.create(
            crop_season=self.season,
            input_type="Fertilizer",
            quantity=Decimal("8"),
            unit="kg",
            application_date=date(2024, 2, 18),
            recorded_by=user,
        )

        user.delete()
        record.refresh_from_db()

        self.assertIsNone(record.recorded_by)

    def test_crop_season_protects_related_input_records(self):
        InputRecord.objects.create(
            crop_season=self.season,
            input_type="Seed",
            quantity=Decimal("5"),
            unit="kg",
            application_date=date(2024, 2, 15),
        )

        with self.assertRaises(ProtectedError):
            self.season.delete()

    def test_application_before_planting_is_allowed(self):
        record = InputRecord(
            crop_season=self.season,
            input_type="Land Prep Input",
            quantity=Decimal("2"),
            unit="kg",
            application_date=date(2024, 1, 5),
        )

        record.full_clean()
        self.assertEqual(record.application_date, date(2024, 1, 5))

    def test_application_after_harvest_is_allowed(self):
        record = InputRecord(
            crop_season=self.season,
            input_type="Cleanup Product",
            quantity=Decimal("1"),
            unit="L",
            application_date=date(2024, 6, 15),
        )

        record.full_clean()
        self.assertEqual(record.application_date, date(2024, 6, 15))

    def test_database_rejects_invalid_quantity_and_blank_required_fields(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InputRecord.objects.bulk_create(
                    [
                        InputRecord(
                            crop_season=self.season,
                            input_type="Fertilizer",
                            quantity=Decimal("0"),
                            unit="kg",
                            application_date=date(2024, 2, 14),
                        )
                    ]
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InputRecord.objects.bulk_create(
                    [
                        InputRecord(
                            crop_season=self.season,
                            input_type="   ",
                            quantity=Decimal("2"),
                            unit="kg",
                            application_date=date(2024, 2, 14),
                        )
                    ]
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InputRecord.objects.bulk_create(
                    [
                        InputRecord(
                            crop_season=self.season,
                            input_type="Fertilizer",
                            quantity=Decimal("2"),
                            unit="   ",
                            application_date=date(2024, 2, 14),
                        )
                    ]
                )


class HarvestBatchModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Harvest Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Harvest Farm")
        self.plot = Plot.objects.create(
            farm=self.farm,
            name="Harvest Plot",
            plot_code="H-001",
        )
        self.season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Harvest Season",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 10),
            actual_planting_date=date(2024, 1, 12),
            expected_harvest_date=date(2024, 6, 1),
            actual_harvest_date=date(2024, 6, 5),
        )

    def test_valid_creation_and_automatic_batch_code_format(self):
        batch = HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("120.5000"),
            farmer_reported_unit="kg",
            notes="First batch.",
        )

        self.assertIsNotNone(batch.pk)
        self.assertRegex(batch.batch_code, r"^FP-[0-9A-F]{12}$")
        self.assertEqual(batch.farmer_reported_unit, "kg")

    def test_uuid_primary_key(self):
        batch = HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 31),
            farmer_reported_quantity=Decimal("50"),
            farmer_reported_unit="kg",
        )

        self.assertTrue(batch.pk)
        self.assertEqual(str(batch.pk), str(batch.pk))

    def test_positive_quantity_required(self):
        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=date(2024, 5, 30),
                farmer_reported_quantity=Decimal("0"),
                farmer_reported_unit="kg",
            ).full_clean()

    def test_zero_and_negative_quantities_are_rejected(self):
        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=date(2024, 5, 30),
                farmer_reported_quantity=Decimal("0.0000"),
                farmer_reported_unit="kg",
            ).full_clean()

        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=date(2024, 5, 30),
                farmer_reported_quantity=Decimal("-1.0000"),
                farmer_reported_unit="kg",
            ).full_clean()

    def test_required_unit_and_whitespace_only_unit_rejected(self):
        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=date(2024, 5, 30),
                farmer_reported_quantity=Decimal("30"),
                farmer_reported_unit="",
            ).full_clean()

        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=date(2024, 5, 30),
                farmer_reported_quantity=Decimal("30"),
                farmer_reported_unit="   ",
            ).full_clean()

    def test_future_harvest_date_is_rejected(self):
        future_date = date.today() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=future_date,
                farmer_reported_quantity=Decimal("30"),
                farmer_reported_unit="kg",
            ).full_clean()

    def test_harvest_before_actual_planting_is_rejected(self):
        with self.assertRaises(ValidationError):
            HarvestBatch(
                crop_season=self.season,
                harvest_date=date(2024, 1, 10),
                farmer_reported_quantity=Decimal("30"),
                farmer_reported_unit="kg",
            ).full_clean()

    def test_harvest_before_planned_planting_is_allowed_when_actual_planting_is_unknown(
        self,
    ):
        other_farm = Farm.objects.create(farmer=self.farmer, name="Independent Farm")
        other_plot = Plot.objects.create(
            farm=other_farm,
            name="Independent Plot",
            plot_code="H-002",
        )
        season_without_actual = CropSeason.objects.create(
            plot=other_plot,
            season_name="No Actual Date",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 20),
            expected_harvest_date=date(2024, 6, 15),
        )

        batch = HarvestBatch(
            crop_season=season_without_actual,
            harvest_date=date(2024, 1, 15),
            farmer_reported_quantity=Decimal("30"),
            farmer_reported_unit="kg",
        )

        batch.full_clean()
        self.assertEqual(batch.harvest_date, date(2024, 1, 15))

    def test_recorded_by_is_optional(self):
        batch = HarvestBatch(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("30"),
            farmer_reported_unit="kg",
        )

        batch.full_clean()
        self.assertIsNone(batch.recorded_by)

    def test_recorded_by_is_set_to_null_when_user_deleted(self):
        user = User.objects.create_user(
            email="harvest@farmproof.test", password="secret"
        )
        batch = HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("30"),
            farmer_reported_unit="kg",
            recorded_by=user,
        )

        user.delete()
        batch.refresh_from_db()

        self.assertIsNone(batch.recorded_by)

    def test_crop_season_delete_is_protected(self):
        HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("30"),
            farmer_reported_unit="kg",
        )

        with self.assertRaises(ProtectedError):
            self.season.delete()

    def test_multiple_batches_in_one_season_and_date_are_allowed(self):
        HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("30"),
            farmer_reported_unit="kg",
        )
        HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("40"),
            farmer_reported_unit="kg",
        )

        self.assertEqual(
            HarvestBatch.objects.filter(crop_season=self.season).count(), 2
        )

    def test_batch_code_cannot_be_changed_after_creation(self):
        batch = HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("30"),
            farmer_reported_unit="kg",
        )

        original_code = batch.batch_code
        batch.batch_code = "FP-1234567890AB"

        with self.assertRaises(ValidationError):
            batch.full_clean()

        batch.batch_code = original_code
        batch.save()
        self.assertEqual(batch.batch_code, original_code)

    def test_database_rejects_invalid_quantity_and_whitespace_only_unit(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HarvestBatch.objects.bulk_create(
                    [
                        HarvestBatch(
                            crop_season=self.season,
                            harvest_date=date(2024, 5, 30),
                            farmer_reported_quantity=Decimal("0"),
                            farmer_reported_unit="kg",
                        )
                    ]
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HarvestBatch.objects.bulk_create(
                    [
                        HarvestBatch(
                            crop_season=self.season,
                            harvest_date=date(2024, 5, 30),
                            farmer_reported_quantity=Decimal("2"),
                            farmer_reported_unit="   ",
                        )
                    ]
                )

    def test_unique_batch_code_collision_retry_works_safely(self):
        first_code = "FP-A83F91C72B04"
        second_code = "FP-9F27D1A6C809"

        with mock.patch.object(
            HarvestBatch,
            "_generate_batch_code",
            return_value=first_code,
        ):
            existing = HarvestBatch.objects.create(
                crop_season=self.season,
                harvest_date=date(2024, 5, 29),
                farmer_reported_quantity=Decimal("10"),
                farmer_reported_unit="kg",
            )

        self.assertEqual(existing.batch_code, first_code)

        with mock.patch.object(
            HarvestBatch,
            "_generate_batch_code",
            side_effect=[first_code, second_code],
        ):
            with transaction.atomic():
                batch = HarvestBatch(
                    crop_season=self.season,
                    harvest_date=date(2024, 5, 30),
                    farmer_reported_quantity=Decimal("30"),
                    farmer_reported_unit="kg",
                )
                batch.save()

                self.assertEqual(batch.batch_code, second_code)
                self.assertEqual(
                    HarvestBatch.objects.get(pk=batch.pk).batch_code, second_code
                )
                existing.refresh_from_db()
                self.assertEqual(existing.batch_code, first_code)

                self.assertEqual(
                    HarvestBatch.objects.filter(pk__in=[existing.pk, batch.pk]).count(),
                    2,
                )

    def test_unrelated_database_errors_propagate_without_retry(self):
        with mock.patch.object(
            HarvestBatch,
            "_generate_batch_code",
            return_value="FP-AAAAAAAAAAAA",
        ) as mock_generate:
            with mock.patch(
                "django.db.models.Model.save",
                side_effect=IntegrityError("unrelated database failure"),
            ):
                batch = HarvestBatch(
                    crop_season=self.season,
                    harvest_date=date(2024, 5, 30),
                    farmer_reported_quantity=Decimal("2"),
                    farmer_reported_unit="kg",
                )

                with self.assertRaises(IntegrityError):
                    batch.save()

        self.assertEqual(mock_generate.call_count, 1)


class QualityInspectionModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Inspection Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Inspection Farm")
        self.plot = Plot.objects.create(
            farm=self.farm,
            name="Inspection Plot",
            plot_code="Q-001",
        )
        self.season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Inspection Season",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 10),
            actual_planting_date=date(2024, 1, 12),
            expected_harvest_date=date(2024, 6, 1),
            actual_harvest_date=date(2024, 6, 5),
        )
        self.batch = HarvestBatch.objects.create(
            crop_season=self.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("120.5000"),
            farmer_reported_unit="kg",
        )
        self.inspector = User.objects.create_user(
            email="inspector@farmproof.test",
            password="secret",
        )
        self._redirect_photo_storage_to_temp_dir()

    def _make_image_bytes(self, image_format="PNG", size=(32, 32), color=(255, 0, 0)):
        buffer = BytesIO()
        Image.new("RGB", size, color).save(buffer, format=image_format)
        return buffer.getvalue()

    def _make_uploaded_photo(
        self, filename, image_format="PNG", size=(32, 32), color=(255, 0, 0)
    ):
        return SimpleUploadedFile(
            name=filename,
            content=self._make_image_bytes(
                image_format=image_format, size=size, color=color
            ),
            content_type=f"image/{image_format.lower()}",
        )

    def _redirect_photo_storage_to_temp_dir(self):
        field = QualityInspection._meta.get_field("photo")
        original_storage = field.storage
        temp_dir = tempfile.mkdtemp(prefix="qualityinspection-test-")
        field.storage = PrivateInspectionStorage(location=temp_dir)
        self.addCleanup(lambda: setattr(field, "storage", original_storage))
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        return field.storage

    def _inspection_datetime(self, year, month, day):
        return datetime(year, month, day, tzinfo=timezone.utc)

    def test_quality_inspection_valid_creation_with_required_photo(self):
        inspection = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible moisture and color appear normal.",
            photo=self._make_uploaded_photo("inspection.png", image_format="PNG"),
        )

        self.assertIsNotNone(inspection.pk)
        self.assertEqual(inspection.harvest_batch, self.batch)
        self.assertEqual(inspection.inspector, self.inspector)

    def test_quality_inspection_uses_uuid_primary_key(self):
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("inspection.png", image_format="PNG"),
        )

        self.assertIsNotNone(inspection.pk)
        self.assertIsInstance(inspection.pk, uuid.UUID)
        self.assertEqual(inspection.pk, inspection.id)

        saved_pk = inspection.pk
        inspection.save()
        self.assertEqual(saved_pk, inspection.pk)

    def test_quality_inspection_relationships_and_default_status(self):
        inspection = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("inspection.png", image_format="PNG"),
        )

        self.assertEqual(inspection.harvest_batch, self.batch)
        self.assertEqual(inspection.inspector, self.inspector)
        self.assertEqual(
            inspection.review_status, QualityInspection.REVIEW_STATUS_RECORDED
        )

    def test_all_approved_review_statuses_are_accepted(self):
        for status in [
            QualityInspection.REVIEW_STATUS_RECORDED,
            QualityInspection.REVIEW_STATUS_REVIEW_REQUIRED,
            QualityInspection.REVIEW_STATUS_REVIEWED,
        ]:
            inspection = QualityInspection(
                harvest_batch=self.batch,
                inspection_date=self._inspection_datetime(2024, 5, 30),
                inspector=self.inspector,
                review_status=status,
                observation_summary="Visible condition was noted.",
                photo=self._make_uploaded_photo(
                    f"inspection-{status}.png", image_format="PNG"
                ),
            )
            inspection.full_clean()
            self.assertEqual(inspection.review_status, status)

    def test_multiple_inspections_can_belong_to_same_batch(self):
        first = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition is acceptable.",
            photo=self._make_uploaded_photo("inspection-1.png", image_format="PNG"),
        )
        second = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 31),
            inspector=self.inspector,
            observation_summary="Visible condition is acceptable.",
            photo=self._make_uploaded_photo("inspection-2.png", image_format="PNG"),
        )

        self.assertEqual(self.batch.inspections.count(), 2)
        self.assertIn(first, self.batch.inspections.all())
        self.assertIn(second, self.batch.inspections.all())

    def test_each_inspection_retains_its_own_photo(self):
        first = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="First note.",
            photo=self._make_uploaded_photo("inspection-first.png", image_format="PNG"),
        )
        second = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 31),
            inspector=self.inspector,
            observation_summary="Second note.",
            photo=self._make_uploaded_photo(
                "inspection-second.png", image_format="PNG"
            ),
        )

        self.assertNotEqual(first.photo.name, second.photo.name)
        self.assertTrue(first.photo.name)
        self.assertTrue(second.photo.name)

    def test_missing_photo_is_rejected(self):
        with self.assertRaises(ValidationError):
            QualityInspection(
                harvest_batch=self.batch,
                inspection_date=self._inspection_datetime(2024, 5, 30),
                inspector=self.inspector,
                observation_summary="Visible condition was noted.",
            ).full_clean()

    def test_missing_observation_summary_is_rejected(self):
        with self.assertRaises(ValidationError):
            QualityInspection(
                harvest_batch=self.batch,
                inspection_date=self._inspection_datetime(2024, 5, 30),
                inspector=self.inspector,
                photo=self._make_uploaded_photo("inspection.png", image_format="PNG"),
            ).full_clean()

    def test_harvest_batch_delete_is_protected_while_inspections_exist(self):
        QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("inspection.png", image_format="PNG"),
        )

        with self.assertRaises(ProtectedError):
            self.batch.delete()

    def test_inspector_delete_is_protected_while_inspections_exist(self):
        QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("inspection.png", image_format="PNG"),
        )

        with self.assertRaises(ProtectedError):
            self.inspector.delete()

    def test_valid_jpeg_upload_is_accepted(self):
        photo = self._make_uploaded_photo("valid.jpg", image_format="JPEG")
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        inspection.full_clean()

    def test_valid_png_upload_is_accepted(self):
        photo = self._make_uploaded_photo("valid.png", image_format="PNG")
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        inspection.full_clean()

    def test_valid_webp_upload_is_accepted(self):
        photo = self._make_uploaded_photo("valid.webp", image_format="WEBP")
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        inspection.full_clean()

    def test_jpg_and_jpeg_extensions_both_accept_jpeg_content(self):
        for filename in ["image.jpg", "image.jpeg"]:
            photo = self._make_uploaded_photo(filename, image_format="JPEG")
            inspection = QualityInspection(
                harvest_batch=self.batch,
                inspection_date=self._inspection_datetime(2024, 5, 30),
                inspector=self.inspector,
                observation_summary="Visible condition was noted.",
                photo=photo,
            )
            inspection.full_clean()

    def test_unsupported_extension_is_rejected(self):
        photo = self._make_uploaded_photo("image.gif", image_format="PNG")
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        with self.assertRaises(ValidationError):
            inspection.full_clean()

    def test_extension_and_content_mismatch_is_rejected(self):
        photo = self._make_uploaded_photo("mismatch.jpg", image_format="PNG")
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        with self.assertRaises(ValidationError):
            inspection.full_clean()

    def test_corrupt_image_data_is_rejected(self):
        photo = SimpleUploadedFile(
            "corrupt.png",
            b"this is definitely not a valid png",
            content_type="image/png",
        )
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        with self.assertRaises(ValidationError):
            inspection.full_clean()

    def test_fake_image_data_with_image_extension_is_rejected(self):
        payload = b"not really an image but extension says png.png"
        photo = SimpleUploadedFile(
            "fake.png",
            payload,
            content_type="image/png",
        )
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        with self.assertRaises(ValidationError):
            inspection.full_clean()

    def test_file_larger_than_8_mb_is_rejected(self):
        payload = b"x" * (8 * 1024 * 1024 + 1)
        photo = SimpleUploadedFile(
            "too_large.png",
            payload,
            content_type="image/png",
        )
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=photo,
        )

        with self.assertRaises(ValidationError):
            inspection.full_clean()

    def test_decompression_bomb_warning_is_rejected_safely(self):
        photo = self._make_uploaded_photo("bomb.png", image_format="PNG")

        class BombingImage:
            def __enter__(self):
                warnings.warn(
                    "decompression bomb warning", Image.DecompressionBombWarning
                )
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with mock.patch("apps.farms.models.Image.open", return_value=BombingImage()):
            inspection = QualityInspection(
                harvest_batch=self.batch,
                inspection_date=self._inspection_datetime(2024, 5, 30),
                inspector=self.inspector,
                observation_summary="Visible condition was noted.",
                photo=photo,
            )

            with self.assertRaises(ValidationError):
                inspection.full_clean()

    def test_decompression_bomb_error_is_rejected_safely(self):
        photo = self._make_uploaded_photo("too_large.png", image_format="PNG")
        with mock.patch(
            "apps.farms.models.Image.open",
            side_effect=Image.DecompressionBombError("too many pixels"),
        ):
            inspection = QualityInspection(
                harvest_batch=self.batch,
                inspection_date=self._inspection_datetime(2024, 5, 30),
                inspector=self.inspector,
                observation_summary="Visible condition was noted.",
                photo=photo,
            )

            with self.assertRaises(ValidationError):
                inspection.full_clean()

    def test_validator_restores_original_file_pointer_position(self):
        photo = self._make_uploaded_photo("pointer.png", image_format="PNG")
        photo.seek(12)
        original_position = photo.tell()

        validate_inspection_photo(photo)

        self.assertEqual(photo.tell(), original_position)

    def test_quality_inspection_photos_are_stored_outside_public_media_root(self):
        storage = self._redirect_photo_storage_to_temp_dir()
        inspection = QualityInspection(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("private.png", image_format="PNG"),
        )

        inspection.save()

        self.assertNotIn(str(settings.MEDIA_ROOT), storage.location)
        self.assertIn("quality_inspections", inspection.photo.name)

    def test_private_storage_url_raises_value_error(self):
        storage = self._redirect_photo_storage_to_temp_dir()
        with self.assertRaises(ValueError):
            storage.url("inspection.png")

    def test_private_storage_permission_modes_are_private(self):
        storage = self._redirect_photo_storage_to_temp_dir()
        self.assertEqual(storage.file_permissions_mode, 0o600)
        self.assertEqual(storage.directory_permissions_mode, 0o700)

    def test_private_storage_saves_distinct_filenames_for_each_inspection(self):
        self._redirect_photo_storage_to_temp_dir()
        first = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 30),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("first.png", image_format="PNG"),
        )
        second = QualityInspection.objects.create(
            harvest_batch=self.batch,
            inspection_date=self._inspection_datetime(2024, 5, 31),
            inspector=self.inspector,
            observation_summary="Visible condition was noted.",
            photo=self._make_uploaded_photo("second.png", image_format="PNG"),
        )

        self.assertNotEqual(first.photo.name, second.photo.name)
        self.assertTrue(first.photo.name.startswith("quality_inspections/"))
        self.assertTrue(second.photo.name.startswith("quality_inspections/"))


class ExpenseRecordModelTests(TestCase):
    def setUp(self):
        self.farmer = FarmerProfile.objects.create(full_name="Expense Farmer")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Expense Farm")
        self.plot = Plot.objects.create(
            farm=self.farm,
            name="Expense Plot",
            plot_code="E-001",
        )
        self.season = CropSeason.objects.create(
            plot=self.plot,
            season_name="Expense Season",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 10),
            actual_planting_date=date(2024, 1, 12),
            expected_harvest_date=date(2024, 6, 1),
            actual_harvest_date=date(2024, 6, 5),
        )

    def test_valid_expense_creation_with_crop_season(self):
        expense = ExpenseRecord.objects.create(
            farm=self.farm,
            crop_season=self.season,
            expense_type="Fertilizer",
            amount=Decimal("1250.50"),
            currency=ExpenseRecord.CURRENCY_LRD,
            expense_date=date(2024, 2, 14),
            vendor_name="Farm Supply Co.",
            description="Applied basal fertilizer.",
        )

        self.assertIsNotNone(expense.pk)
        self.assertEqual(expense.expense_type, "Fertilizer")

    def test_valid_expense_creation_without_crop_season(self):
        expense = ExpenseRecord.objects.create(
            farm=self.farm,
            expense_type="Fuel",
            amount=Decimal("550.00"),
            currency=ExpenseRecord.CURRENCY_USD,
            expense_date=date(2024, 2, 18),
            vendor_name="Local Dealer",
            description="Fuel for transport.",
        )

        self.assertIsNotNone(expense.pk)
        self.assertEqual(expense.currency, ExpenseRecord.CURRENCY_USD)

    def test_zero_amount_rejected(self):
        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                expense_type="Fuel",
                amount=Decimal("0.00"),
                currency=ExpenseRecord.CURRENCY_LRD,
                expense_date=date(2024, 2, 14),
            ).full_clean()

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                expense_type="Fuel",
                amount=Decimal("-10.00"),
                currency=ExpenseRecord.CURRENCY_LRD,
                expense_date=date(2024, 2, 14),
            ).full_clean()

    def test_whitespace_only_expense_type_rejected(self):
        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                expense_type="   ",
                amount=Decimal("25.00"),
                currency=ExpenseRecord.CURRENCY_LRD,
                expense_date=date(2024, 2, 14),
            ).full_clean()

    def test_missing_expense_type_rejected(self):
        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                expense_type="",
                amount=Decimal("25.00"),
                currency=ExpenseRecord.CURRENCY_LRD,
                expense_date=date(2024, 2, 14),
            ).full_clean()

    def test_invalid_currency_rejected(self):
        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                expense_type="Fuel",
                amount=Decimal("25.00"),
                currency="EUR",
                expense_date=date(2024, 2, 14),
            ).full_clean()

    def test_future_expense_date_rejected(self):
        future_date = date.today() + timedelta(days=1)
        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                expense_type="Fuel",
                amount=Decimal("25.00"),
                currency=ExpenseRecord.CURRENCY_USD,
                expense_date=future_date,
            ).full_clean()

    def test_recorded_by_is_optional(self):
        expense = ExpenseRecord(
            farm=self.farm,
            expense_type="Seed",
            amount=Decimal("30.00"),
            currency=ExpenseRecord.CURRENCY_LRD,
            expense_date=date(2024, 2, 20),
        )

        expense.full_clean()
        self.assertIsNone(expense.recorded_by)

    def test_recorded_by_is_set_to_null_when_user_deleted(self):
        user = User.objects.create_user(
            email="expense@farmproof.test", password="secret"
        )
        expense = ExpenseRecord.objects.create(
            farm=self.farm,
            crop_season=self.season,
            expense_type="Seed",
            amount=Decimal("30.00"),
            currency=ExpenseRecord.CURRENCY_LRD,
            expense_date=date(2024, 2, 18),
            recorded_by=user,
        )

        user.delete()
        expense.refresh_from_db()

        self.assertIsNone(expense.recorded_by)

    def test_farm_delete_is_protected(self):
        ExpenseRecord.objects.create(
            farm=self.farm,
            expense_type="Fuel",
            amount=Decimal("50.00"),
            currency=ExpenseRecord.CURRENCY_USD,
            expense_date=date(2024, 2, 15),
        )

        with self.assertRaises(ProtectedError):
            self.farm.delete()

    def test_crop_season_delete_is_protected(self):
        ExpenseRecord.objects.create(
            farm=self.farm,
            crop_season=self.season,
            expense_type="Fertilizer",
            amount=Decimal("100.00"),
            currency=ExpenseRecord.CURRENCY_LRD,
            expense_date=date(2024, 2, 15),
        )

        with self.assertRaises(ProtectedError):
            self.season.delete()

    def test_crop_season_must_belong_to_same_farm(self):
        other_farm = Farm.objects.create(farmer=self.farmer, name="Other Farm")
        other_plot = Plot.objects.create(
            farm=other_farm,
            name="Other Plot",
            plot_code="E-002",
        )
        other_season = CropSeason.objects.create(
            plot=other_plot,
            season_name="Wrong Farm Season",
            crop_type="Rice",
            planned_planting_date=date(2024, 1, 10),
            expected_harvest_date=date(2024, 6, 1),
        )

        with self.assertRaises(ValidationError):
            ExpenseRecord(
                farm=self.farm,
                crop_season=other_season,
                expense_type="Fuel",
                amount=Decimal("25.00"),
                currency=ExpenseRecord.CURRENCY_USD,
                expense_date=date(2024, 2, 14),
            ).full_clean()

    def test_lrd_and_usd_are_accepted(self):
        ExpenseRecord(
            farm=self.farm,
            expense_type="Fuel",
            amount=Decimal("25.00"),
            currency=ExpenseRecord.CURRENCY_LRD,
            expense_date=date(2024, 2, 14),
        ).full_clean()

        ExpenseRecord(
            farm=self.farm,
            expense_type="Fuel",
            amount=Decimal("25.00"),
            currency=ExpenseRecord.CURRENCY_USD,
            expense_date=date(2024, 2, 14),
        ).full_clean()

    def test_database_rejects_invalid_amounts_and_currency_and_blank_type(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExpenseRecord.objects.bulk_create(
                    [
                        ExpenseRecord(
                            farm=self.farm,
                            expense_type="Fuel",
                            amount=Decimal("0.00"),
                            currency=ExpenseRecord.CURRENCY_LRD,
                            expense_date=date(2024, 2, 14),
                        )
                    ]
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExpenseRecord.objects.bulk_create(
                    [
                        ExpenseRecord(
                            farm=self.farm,
                            expense_type="Fuel",
                            amount=Decimal("-1.00"),
                            currency=ExpenseRecord.CURRENCY_LRD,
                            expense_date=date(2024, 2, 14),
                        )
                    ]
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExpenseRecord.objects.bulk_create(
                    [
                        ExpenseRecord(
                            farm=self.farm,
                            expense_type="Fuel",
                            amount=Decimal("10.00"),
                            currency="EUR",
                            expense_date=date(2024, 2, 14),
                        )
                    ]
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExpenseRecord.objects.bulk_create(
                    [
                        ExpenseRecord(
                            farm=self.farm,
                            expense_type="   ",
                            amount=Decimal("10.00"),
                            currency=ExpenseRecord.CURRENCY_USD,
                            expense_date=date(2024, 2, 14),
                        )
                    ]
                )
