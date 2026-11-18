from contextlib import contextmanager
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.farmers.models import FarmerContact, FarmerIDSequence, FarmerProfile


class FarmerProfileModelTests(TestCase):
    def test_farmer_profile_requires_unique_farmer_id(self):
        FarmerProfile.objects.create(farmer_id="F-1001", full_name="Ada Farmer")

        with self.assertRaises(IntegrityError):
            FarmerProfile.objects.create(farmer_id="F-1001", full_name="Another Farmer")

    def test_farmer_profile_auto_generates_fp_ids(self):
        first = FarmerProfile.objects.create(full_name="Auto Farmer One")
        second = FarmerProfile.objects.create(full_name="Auto Farmer Two")

        self.assertEqual(first.farmer_id, "FP-000001")
        self.assertEqual(second.farmer_id, "FP-000002")

    def test_allocates_farmer_ids_from_sequence_row(self):
        sequence, _ = FarmerIDSequence.objects.get_or_create(key="farmer_profile")
        sequence.last_value = 0
        sequence.save(update_fields=["last_value"])

        self.assertEqual(FarmerProfile.allocate_farmer_id(), "FP-000001")
        self.assertEqual(FarmerProfile.allocate_farmer_id(), "FP-000002")

    def test_retries_if_id_allocation_conflicts(self):
        calls = {"count": 0}

        @contextmanager
        def atomic_retry(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise IntegrityError(
                    "UNIQUE constraint failed: farmers_farmerprofile.farmer_id"
                )
            yield

        with mock.patch("apps.farmers.models.transaction.atomic", new=atomic_retry):
            self.assertEqual(FarmerProfile.allocate_farmer_id(), "FP-000001")

    def test_manual_fp_namespace_is_rejected(self):
        with self.assertRaises(ValidationError):
            FarmerProfile.objects.create(farmer_id="FP-000001", full_name="Manual FP")

    def test_update_existing_farmer_full_name_is_allowed(self):
        farmer = FarmerProfile.objects.create(
            farmer_id="F-1002", full_name="Before Update"
        )

        farmer.full_name = "After Update"
        farmer.save()

        self.assertEqual(
            FarmerProfile.objects.get(pk=farmer.pk).full_name,
            "After Update",
        )

    def test_update_existing_farmer_status_is_allowed(self):
        farmer = FarmerProfile.objects.create(
            farmer_id="F-1003", full_name="Status Farmer"
        )

        farmer.status = FarmerProfile.STATUS_INACTIVE
        farmer.save()

        self.assertEqual(
            FarmerProfile.objects.get(pk=farmer.pk).status,
            FarmerProfile.STATUS_INACTIVE,
        )

    def test_rejects_changes_to_existing_farmer_id(self):
        farmer = FarmerProfile.objects.create(full_name="Immutable Farmer")

        with self.assertRaises(ValidationError):
            farmer.farmer_id = "FP-000002"
            farmer.save()

    def test_rejects_clearing_existing_farmer_id(self):
        farmer = FarmerProfile.objects.create(full_name="Clear Farmer")

        with self.assertRaises(ValidationError):
            farmer.farmer_id = ""
            farmer.save()

    def test_farmer_creation_inside_outer_transaction_is_safe(self):
        with transaction.atomic():
            profile = FarmerProfile.objects.create(
                full_name="Nested Transaction Farmer"
            )
            self.assertTrue(profile.farmer_id.startswith("FP-"))

    def test_allocation_conflict_retries_during_real_save_in_outer_transaction(self):
        existing = FarmerProfile.objects.create(full_name="Existing Farmer")
        self.assertEqual(existing.farmer_id, "FP-000001")

        with transaction.atomic():
            candidate_ids = iter(["FP-000001", "FP-000002"])

            with mock.patch.object(
                FarmerProfile,
                "allocate_farmer_id",
                side_effect=lambda: next(candidate_ids),
            ):
                profile = FarmerProfile(full_name="Conflict Retry Farmer")
                profile.save()

            self.assertEqual(profile.farmer_id, "FP-000002")
            self.assertEqual(
                FarmerProfile.objects.filter(full_name="Conflict Retry Farmer").count(),
                1,
            )
            self.assertEqual(
                FarmerProfile.objects.get(pk=profile.pk).farmer_id,
                "FP-000002",
            )

    def test_non_lock_operational_error_is_not_retried(self):
        calls = {"count": 0}

        @contextmanager
        def atomic_retry(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise OperationalError("syntax error in SQL")
            yield

        with mock.patch("apps.farmers.models.transaction.atomic", new=atomic_retry):
            with self.assertRaises(OperationalError):
                FarmerProfile.allocate_farmer_id()

    def test_farmer_contact_primary_constraint_allows_only_one_primary_per_farmer(self):
        farmer = FarmerProfile.objects.create(
            farmer_id="F-1002", full_name="Grace Farmer"
        )
        FarmerContact.objects.create(
            farmer=farmer,
            phone_number="+254700000001",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )

        second = FarmerContact(
            farmer=farmer,
            phone_number="+254700000002",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )
        with self.assertRaises(ValidationError):
            second.full_clean()

    def test_farmer_contact_can_share_phone_number_between_farmers(self):
        first = FarmerProfile.objects.create(
            farmer_id="F-1003", full_name="First Farmer"
        )
        second = FarmerProfile.objects.create(
            farmer_id="F-1004", full_name="Second Farmer"
        )

        FarmerContact.objects.create(
            farmer=first,
            phone_number="+254700000003",
            contact_type=FarmerContact.CONTACT_TYPE_SHARED,
        )
        FarmerContact.objects.create(
            farmer=second,
            phone_number="+254700000003",
            contact_type=FarmerContact.CONTACT_TYPE_SHARED,
        )

        self.assertEqual(
            FarmerContact.objects.filter(phone_number="+254700000003").count(),
            2,
        )

    def test_shared_contact_cannot_be_primary(self):
        farmer = FarmerProfile.objects.create(
            farmer_id="F-1005", full_name="Shared Farmer"
        )
        contact = FarmerContact(
            farmer=farmer,
            phone_number="+254700000004",
            contact_type=FarmerContact.CONTACT_TYPE_SHARED,
            is_primary=True,
        )

        with self.assertRaises(ValidationError):
            contact.full_clean()

    def test_farmer_profile_can_link_to_user_without_taking_over_authentication(self):
        user = User.objects.create_user(
            email="farmer@example.com", password="StrongPass123!"
        )
        profile = FarmerProfile.objects.create(
            farmer_id="F-1006",
            full_name="Farmer with User",
            user=user,
        )

        self.assertEqual(profile.user, user)
        self.assertEqual(user.farmer_profile, profile)

    def test_phone_number_normalization_handles_international_format(self):
        self.assertEqual(
            FarmerContact.normalize_phone_number("+254 712 345 678"),
            "+254712345678",
        )

    def test_phone_number_normalization_handles_00_prefix_format(self):
        self.assertEqual(
            FarmerContact.normalize_phone_number("00 254 712 345 678"),
            "+254712345678",
        )

    def test_phone_number_normalization_removes_common_formatting_without_inventing_country_code(
        self,
    ):
        self.assertEqual(
            FarmerContact.normalize_phone_number("(077) 123-4567"),
            "0771234567",
        )

    def test_phone_number_normalization_converts_liberian_local_numbers_when_country_known(
        self,
    ):
        self.assertEqual(
            FarmerContact.normalize_phone_number("0771234567", country_code="LR"),
            "+231771234567",
        )

    def test_phone_number_normalization_does_not_assume_liberia_without_country_context(
        self,
    ):
        self.assertEqual(
            FarmerContact.normalize_phone_number("0771234567"),
            "0771234567",
        )

    def test_phone_number_rejects_alphabetic_characters(self):
        contact = FarmerContact(
            farmer=FarmerProfile.objects.create(
                farmer_id="F-1008",
                full_name="Bad Phone Farmer",
            ),
            phone_number="abc123",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )

        with self.assertRaises(ValidationError):
            contact.full_clean()

    def test_phone_number_rejects_misplaced_plus_sign(self):
        contact = FarmerContact(
            farmer=FarmerProfile.objects.create(
                farmer_id="F-1009",
                full_name="Plus Sign Farmer",
            ),
            phone_number="077+1234567",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )

        with self.assertRaises(ValidationError):
            contact.full_clean()

    def test_phone_number_rejects_empty_international_prefix(self):
        contact = FarmerContact(
            farmer=FarmerProfile.objects.create(
                farmer_id="F-1010",
                full_name="Empty Prefix Farmer",
            ),
            phone_number="+",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )

        with self.assertRaises(ValidationError):
            contact.full_clean()

    def test_phone_number_rejects_unsupported_symbols(self):
        contact = FarmerContact(
            farmer=FarmerProfile.objects.create(
                farmer_id="F-1011",
                full_name="Unsupported Symbol Farmer",
            ),
            phone_number="077@123-4567",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )

        with self.assertRaises(ValidationError):
            contact.full_clean()


class FarmerContactModelTests(TestCase):
    def test_primary_contact_requires_phone_number(self):
        farmer = FarmerProfile.objects.create(
            farmer_id="F-1007", full_name="Phone Farmer"
        )
        contact = FarmerContact(
            farmer=farmer,
            phone_number="",
            contact_type=FarmerContact.CONTACT_TYPE_PERSONAL,
            is_primary=True,
        )

        with self.assertRaises(ValidationError):
            contact.full_clean()
