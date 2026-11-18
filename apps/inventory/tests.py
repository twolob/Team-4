from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.cooperatives.models import Cooperative
from apps.farmers.models import FarmerProfile
from apps.farms.models import CropSeason, Farm, HarvestBatch, Plot
from apps.inventory.models import (
    CoopIntake,
    LossRecord,
    StockMovement,
    StorageLocation,
    TransferLine,
    TransferRecord,
)


class StockMovementModelTests(TestCase):
    """Model-specific tests for the StockMovement implementation."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="recorder@farmproof.test", password="StrongPass123!"
        )
        cls.cooperative = Cooperative.objects.create(name="Green Valley Cooperative")
        cls.storage_location = StorageLocation.objects.create(
            cooperative=cls.cooperative,
            name="Main Warehouse",
            code="WH-01",
        )
        cls.second_location = StorageLocation.objects.create(
            cooperative=cls.cooperative,
            name="Annex",
            code="WH-02",
        )

        cls.farmer = FarmerProfile.objects.create(full_name="John Farmer")
        cls.farm = Farm.objects.create(farmer=cls.farmer, name="North Farm")
        cls.plot = Plot.objects.create(
            farm=cls.farm, name="Plot A", plot_code="P-A"
        )
        cls.season = CropSeason.objects.create(
            plot=cls.plot,
            season_name="2024 Season",
            crop_type="Maize",
            planned_planting_date=date(2024, 1, 10),
        )
        cls.harvest_batch = HarvestBatch.objects.create(
            crop_season=cls.season,
            harvest_date=date(2024, 5, 30),
            farmer_reported_quantity=Decimal("1000.0000"),
            farmer_reported_unit="kg",
        )

        cls.coop_intake = CoopIntake.objects.create(
            harvest_batch=cls.harvest_batch,
            cooperative=cls.cooperative,
            storage_location=cls.storage_location,
            received_quantity=Decimal("500.0000"),
            received_unit="kg",
            intake_date=timezone.now(),
            recorded_by=cls.user,
        )

        cls.original_coop_intake = CoopIntake.objects.create(
            harvest_batch=cls.harvest_batch,
            cooperative=cls.cooperative,
            storage_location=cls.storage_location,
            received_quantity=Decimal("100.0000"),
            received_unit="kg",
            intake_date=timezone.now() - timedelta(days=2),
            recorded_by=cls.user,
        )

        cls.transfer_record = TransferRecord.objects.create(
            cooperative=cls.cooperative,
            requested_by=cls.user,
            source_storage_location=cls.storage_location,
            destination_storage_location=cls.second_location,
        )
        cls.transfer_line = TransferLine.objects.create(
            transfer_record=cls.transfer_record,
            harvest_batch=cls.harvest_batch,
            expected_quantity=Decimal("400.0000"),
            expected_unit="kg",
        )

        cls.warehouse_loss = LossRecord.objects.create(
            harvest_batch=cls.harvest_batch,
            loss_type="warehouse_loss",
            quantity=Decimal("20.0000"),
            unit="kg",
            reason_category="spoilage",
            notes="Test warehouse loss",
            recorded_by=cls.user,
            storage_location=cls.storage_location,
        )
        cls.transit_loss = LossRecord.objects.create(
            harvest_batch=cls.harvest_batch,
            loss_type="transit_loss",
            quantity=Decimal("10.0000"),
            unit="kg",
            reason_category="spoilage",
            notes="Test transit loss",
            recorded_by=cls.user,
            transfer_line=cls.transfer_line,
        )

        cls.original_movement = StockMovement.objects.create(
            movement_type=StockMovement.MOVEMENT_INBOUND_INTAKE,
            coop_intake=cls.original_coop_intake,
            destination_storage_location=cls.storage_location,
            quantity=Decimal("100.0000"),
            unit="kg",
            occurred_at=timezone.now() - timedelta(days=2),
        )

        cls.past_moment = timezone.now() - timedelta(days=1)
        cls.future_moment = timezone.now() + timedelta(days=1)

    # -- helpers ---------------------------------------------------------

    def _movement_kwargs(self, movement_type, **overrides):
        kwargs = {
            "movement_type": movement_type,
            "quantity": Decimal("10.0000"),
            "unit": "kg",
            "occurred_at": self.past_moment,
        }
        required_by_type = {
            StockMovement.MOVEMENT_INBOUND_INTAKE: {
                "coop_intake": self.coop_intake,
                "destination_storage_location": self.storage_location,
            },
            StockMovement.MOVEMENT_DISPATCH: {
                "transfer_line": self.transfer_line,
                "source_storage_location": self.storage_location,
            },
            StockMovement.MOVEMENT_RECEIPT: {
                "transfer_line": self.transfer_line,
                "destination_storage_location": self.storage_location,
            },
            StockMovement.MOVEMENT_WAREHOUSE_LOSS: {
                "loss_record": self.warehouse_loss,
                "source_storage_location": self.storage_location,
            },
            StockMovement.MOVEMENT_TRANSIT_LOSS: {
                "loss_record": self.transit_loss,
                "transfer_line": self.transfer_line,
            },
        }
        if movement_type in required_by_type:
            kwargs.update(required_by_type[movement_type])
        elif movement_type in {
            StockMovement.MOVEMENT_CORRECTION,
            StockMovement.MOVEMENT_REVERSAL,
        }:
            kwargs["original_movement"] = self.original_movement
        kwargs.update(overrides)
        return kwargs

    def _build_movement(self, movement_type, **overrides):
        return StockMovement(**self._movement_kwargs(movement_type, **overrides))

    def _create_movement(self, movement_type, **overrides):
        return StockMovement.objects.create(**self._movement_kwargs(movement_type, **overrides))

    def _assert_invalid(self, movement_type, **overrides):
        movement = self._build_movement(movement_type, **overrides)
        with self.assertRaises(ValidationError):
            movement.full_clean()

    def _assert_valid(self, movement_type, **overrides):
        movement = self._build_movement(movement_type, **overrides)
        movement.full_clean()

    # -- 1. Valid movement creation -------------------------------------

    def test_all_seven_movement_types_can_be_created(self):
        for movement_type, _label in StockMovement.MOVEMENT_CHOICES:
            with self.subTest(movement_type=movement_type):
                movement = self._create_movement(movement_type)
                self.assertIsNotNone(movement.pk)
                self.assertEqual(movement.movement_type, movement_type)
                self.assertTrue(
                    StockMovement.objects.filter(pk=movement.pk).exists()
                )

    def test_movement_type_constants_match_approved_list(self):
        self.assertEqual(
            [code for code, _label in StockMovement.MOVEMENT_CHOICES],
            [
                StockMovement.MOVEMENT_INBOUND_INTAKE,
                StockMovement.MOVEMENT_DISPATCH,
                StockMovement.MOVEMENT_RECEIPT,
                StockMovement.MOVEMENT_WAREHOUSE_LOSS,
                StockMovement.MOVEMENT_TRANSIT_LOSS,
                StockMovement.MOVEMENT_CORRECTION,
                StockMovement.MOVEMENT_REVERSAL,
            ],
        )

    # -- 2. Relationship validation -------------------------------------

    def test_missing_mandatory_relationship_is_rejected(self):
        cases = [
            (StockMovement.MOVEMENT_INBOUND_INTAKE, {"coop_intake": None}),
            (
                StockMovement.MOVEMENT_INBOUND_INTAKE,
                {"destination_storage_location": None},
            ),
            (StockMovement.MOVEMENT_DISPATCH, {"transfer_line": None}),
            (StockMovement.MOVEMENT_DISPATCH, {"source_storage_location": None}),
            (StockMovement.MOVEMENT_RECEIPT, {"transfer_line": None}),
            (
                StockMovement.MOVEMENT_RECEIPT,
                {"destination_storage_location": None},
            ),
            (StockMovement.MOVEMENT_WAREHOUSE_LOSS, {"loss_record": None}),
            (
                StockMovement.MOVEMENT_WAREHOUSE_LOSS,
                {"source_storage_location": None},
            ),
            (StockMovement.MOVEMENT_TRANSIT_LOSS, {"loss_record": None}),
            (StockMovement.MOVEMENT_TRANSIT_LOSS, {"transfer_line": None}),
            (StockMovement.MOVEMENT_CORRECTION, {"original_movement": None}),
            (StockMovement.MOVEMENT_REVERSAL, {"original_movement": None}),
        ]
        for movement_type, overrides in cases:
            with self.subTest(movement_type=movement_type):
                self._assert_invalid(movement_type, **overrides)

    def test_forbidden_unrelated_relationship_is_rejected(self):
        cases = [
            # inbound_intake forbids source, transfer_line, loss_record,
            # original_movement
            (
                StockMovement.MOVEMENT_INBOUND_INTAKE,
                {"source_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_INBOUND_INTAKE,
                {"transfer_line": self.transfer_line},
            ),
            (
                StockMovement.MOVEMENT_INBOUND_INTAKE,
                {"loss_record": self.warehouse_loss},
            ),
            (
                StockMovement.MOVEMENT_INBOUND_INTAKE,
                {"original_movement": self.original_movement},
            ),
            # transfer_dispatch forbids destination, loss_record, coop_intake,
            # original_movement
            (
                StockMovement.MOVEMENT_DISPATCH,
                {"destination_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_DISPATCH,
                {"loss_record": self.warehouse_loss},
            ),
            (StockMovement.MOVEMENT_DISPATCH, {"coop_intake": self.coop_intake}),
            (
                StockMovement.MOVEMENT_DISPATCH,
                {"original_movement": self.original_movement},
            ),
            # transfer_receipt forbids source, loss_record, coop_intake,
            # original_movement
            (
                StockMovement.MOVEMENT_RECEIPT,
                {"source_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_RECEIPT,
                {"loss_record": self.warehouse_loss},
            ),
            (StockMovement.MOVEMENT_RECEIPT, {"coop_intake": self.coop_intake}),
            (
                StockMovement.MOVEMENT_RECEIPT,
                {"original_movement": self.original_movement},
            ),
        ]
        for movement_type, _overrides in cases:
            with self.subTest(movement_type=movement_type):
                self._assert_invalid(movement_type, **_overrides)

    def test_forbidden_unrelated_relationship_loss_and_correction(self):
        cases = [
            # warehouse_loss forbids destination, transfer_line, coop_intake,
            # original_movement
            (
                StockMovement.MOVEMENT_WAREHOUSE_LOSS,
                {"destination_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_WAREHOUSE_LOSS,
                {"transfer_line": self.transfer_line},
            ),
            (
                StockMovement.MOVEMENT_WAREHOUSE_LOSS,
                {"coop_intake": self.coop_intake},
            ),
            (
                StockMovement.MOVEMENT_WAREHOUSE_LOSS,
                {"original_movement": self.original_movement},
            ),
            # transit_loss forbids source, destination, coop_intake,
            # original_movement
            (
                StockMovement.MOVEMENT_TRANSIT_LOSS,
                {"source_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_TRANSIT_LOSS,
                {"destination_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_TRANSIT_LOSS,
                {"coop_intake": self.coop_intake},
            ),
            (
                StockMovement.MOVEMENT_TRANSIT_LOSS,
                {"original_movement": self.original_movement},
            ),
            # correction/reversal forbid coop_intake, transfer_line,
            # loss_record, source, destination
            (
                StockMovement.MOVEMENT_CORRECTION,
                {"coop_intake": self.coop_intake},
            ),
            (
                StockMovement.MOVEMENT_CORRECTION,
                {"transfer_line": self.transfer_line},
            ),
            (
                StockMovement.MOVEMENT_CORRECTION,
                {"loss_record": self.warehouse_loss},
            ),
            (
                StockMovement.MOVEMENT_CORRECTION,
                {"source_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_CORRECTION,
                {"destination_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_REVERSAL,
                {"coop_intake": self.coop_intake},
            ),
            (
                StockMovement.MOVEMENT_REVERSAL,
                {"transfer_line": self.transfer_line},
            ),
            (
                StockMovement.MOVEMENT_REVERSAL,
                {"loss_record": self.warehouse_loss},
            ),
            (
                StockMovement.MOVEMENT_REVERSAL,
                {"source_storage_location": self.second_location},
            ),
            (
                StockMovement.MOVEMENT_REVERSAL,
                {"destination_storage_location": self.second_location},
            ),
        ]
        for movement_type, _overrides in cases:
            with self.subTest(movement_type=movement_type):
                self._assert_invalid(movement_type, **_overrides)

    def test_complete_approved_relationship_matrix_is_valid(self):
        for movement_type, _label in StockMovement.MOVEMENT_CHOICES:
            with self.subTest(movement_type=movement_type):
                movement = self._create_movement(movement_type)
                self.assertIsNotNone(movement.pk)
                self.assertTrue(
                    StockMovement.objects.filter(pk=movement.pk).exists()
                )

    # -- 3. Quantity and unit -------------------------------------------

    def test_zero_quantity_is_rejected(self):
        self._assert_invalid(
            StockMovement.MOVEMENT_INBOUND_INTAKE, quantity=Decimal("0")
        )

    def test_negative_quantity_is_rejected(self):
        self._assert_invalid(
            StockMovement.MOVEMENT_INBOUND_INTAKE, quantity=Decimal("-5.0000")
        )

    def test_positive_quantity_is_accepted(self):
        self._assert_valid(
            StockMovement.MOVEMENT_INBOUND_INTAKE, quantity=Decimal("0.0001")
        )

    def test_blank_unit_is_rejected(self):
        self._assert_invalid(
            StockMovement.MOVEMENT_INBOUND_INTAKE, unit=""
        )

    def test_whitespace_only_unit_is_rejected(self):
        self._assert_invalid(
            StockMovement.MOVEMENT_INBOUND_INTAKE, unit="   "
        )

    def test_valid_unit_is_accepted(self):
        self._assert_valid(
            StockMovement.MOVEMENT_INBOUND_INTAKE, unit="kg"
        )

    # -- 4. Date validation ---------------------------------------------

    def test_future_occurred_at_is_rejected(self):
        self._assert_invalid(
            StockMovement.MOVEMENT_INBOUND_INTAKE,
            occurred_at=self.future_moment,
        )

    def test_past_occurred_at_is_accepted(self):
        self._assert_valid(
            StockMovement.MOVEMENT_INBOUND_INTAKE,
            occurred_at=self.past_moment,
        )

    def test_current_occurred_at_is_accepted(self):
        self._assert_valid(
            StockMovement.MOVEMENT_INBOUND_INTAKE,
            occurred_at=timezone.now(),
        )

    # -- 5. Immutability ------------------------------------------------

    def test_save_rejects_changes_to_persisted_movement(self):
        movement = self._create_movement(StockMovement.MOVEMENT_INBOUND_INTAKE)
        original_pk = movement.pk
        movement.quantity = Decimal("999.0000")
        with self.assertRaises(ValidationError):
            movement.save()
        movement.refresh_from_db()
        self.assertEqual(movement.quantity, Decimal("10.0000"))
        self.assertEqual(movement.pk, original_pk)

    def test_delete_rejects_persisted_movement(self):
        movement = self._create_movement(StockMovement.MOVEMENT_INBOUND_INTAKE)
        pk = movement.pk
        with self.assertRaises(ValidationError):
            movement.delete()
        self.assertTrue(StockMovement.objects.filter(pk=pk).exists())

    def test_uuid_reuse_save_is_rejected(self):
        existing = self._create_movement(StockMovement.MOVEMENT_INBOUND_INTAKE)
        reuse = StockMovement(
            id=existing.id,
            movement_type=StockMovement.MOVEMENT_DISPATCH,
            transfer_line=self.transfer_line,
            source_storage_location=self.storage_location,
            quantity=Decimal("5.0000"),
            unit="kg",
            occurred_at=self.past_moment,
        )
        with self.assertRaises(ValidationError):
            reuse.save()
        self.assertTrue(StockMovement.objects.filter(pk=existing.id).exists())

    def test_uuid_reuse_delete_is_rejected(self):
        existing = self._create_movement(StockMovement.MOVEMENT_INBOUND_INTAKE)
        reuse = StockMovement(
            id=existing.id,
            movement_type=StockMovement.MOVEMENT_DISPATCH,
            transfer_line=self.transfer_line,
            source_storage_location=self.storage_location,
            quantity=Decimal("5.0000"),
            unit="kg",
            occurred_at=self.past_moment,
        )
        with self.assertRaises(ValidationError):
            reuse.delete()
        self.assertTrue(StockMovement.objects.filter(pk=existing.id).exists())

    def test_new_unused_uuid_can_be_saved(self):
        existing = self._create_movement(StockMovement.MOVEMENT_INBOUND_INTAKE)
        movement = self._create_movement(StockMovement.MOVEMENT_RECEIPT)
        self.assertIsNotNone(movement.pk)
        self.assertNotEqual(movement.pk, existing.pk)
        self.assertTrue(StockMovement.objects.filter(pk=movement.pk).exists())

    # -- 6. Corrections and reversals -----------------------------------

    def test_valid_correction_referencing_original_is_accepted(self):
        movement = self._create_movement(
            StockMovement.MOVEMENT_CORRECTION, quantity=Decimal("30.0000")
        )
        self.assertIsNotNone(movement.pk)
        self.assertEqual(movement.original_movement, self.original_movement)

    def test_valid_reversal_referencing_original_is_accepted(self):
        movement = self._create_movement(
            StockMovement.MOVEMENT_REVERSAL, quantity=Decimal("100.0000")
        )
        self.assertIsNotNone(movement.pk)
        self.assertEqual(movement.original_movement, self.original_movement)

    def test_partial_correction_quantity_is_accepted(self):
        movement = self._create_movement(
            StockMovement.MOVEMENT_CORRECTION, quantity=Decimal("30.0000")
        )
        self.assertIsNotNone(movement.pk)
        self.assertLess(movement.quantity, self.original_movement.quantity)

    def test_correction_does_not_require_original_full_quantity(self):
        movement = self._create_movement(
            StockMovement.MOVEMENT_CORRECTION, quantity=Decimal("10.0000")
        )
        self.assertIsNotNone(movement.pk)
        self.assertNotEqual(movement.quantity, self.original_movement.quantity)
