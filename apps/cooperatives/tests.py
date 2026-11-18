from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import User
from apps.cooperatives.models import (
    Cooperative,
    CooperativeMembership,
    CooperativeStaffMembership,
)
from apps.farmers.models import FarmerProfile


class CooperativeModelTests(TestCase):
    def test_cooperative_name_is_unique(self):
        Cooperative.objects.create(name="Nakuru Cooperative")

        with self.assertRaises(IntegrityError):
            Cooperative.objects.create(name="Nakuru Cooperative")

    def test_cooperative_membership_requires_one_farmer_once_per_cooperative(self):
        cooperative = Cooperative.objects.create(name="Mwea Cooperative")
        farmer = FarmerProfile.objects.create(
            farmer_id="F-2001", full_name="Farmer One"
        )
        CooperativeMembership.objects.create(cooperative=cooperative, farmer=farmer)

        duplicate = CooperativeMembership(cooperative=cooperative, farmer=farmer)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_staff_membership_requires_distinct_user_cooperative_pair(self):
        user = User.objects.create_user(
            email="staff@example.com", password="StrongPass123!"
        )
        cooperative = Cooperative.objects.create(name="Kisumu Cooperative")
        CooperativeStaffMembership.objects.create(user=user, cooperative=cooperative)

        duplicate = CooperativeStaffMembership(user=user, cooperative=cooperative)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_membership_status_can_deactivate_without_removing_history(self):
        cooperative = Cooperative.objects.create(name="Bungoma Cooperative")
        farmer = FarmerProfile.objects.create(
            farmer_id="F-2002", full_name="Inactive Member"
        )
        membership = CooperativeMembership.objects.create(
            cooperative=cooperative,
            farmer=farmer,
            status=CooperativeMembership.STATUS_INACTIVE,
        )

        self.assertEqual(membership.status, CooperativeMembership.STATUS_INACTIVE)
        self.assertEqual(
            CooperativeMembership.objects.filter(
                farmer=farmer, cooperative=cooperative
            ).count(),
            1,
        )

    def test_staff_role_uses_controlled_choices(self):
        user = User.objects.create_user(
            email="role@example.com", password="StrongPass123!"
        )
        cooperative = Cooperative.objects.create(name="Siaya Cooperative")
        membership = CooperativeStaffMembership.objects.create(
            user=user,
            cooperative=cooperative,
            role=CooperativeStaffMembership.ROLE_MANAGER,
        )

        self.assertEqual(membership.role, CooperativeStaffMembership.ROLE_MANAGER)
        self.assertIn(membership.role, dict(CooperativeStaffMembership.ROLE_CHOICES))
