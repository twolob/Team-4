from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.farmers.models import FarmerProfile


class Cooperative(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="unique_cooperative_name",
            )
        ]

    def __str__(self):
        return self.name


class CooperativeMembership(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    farmer = models.ForeignKey(
        FarmerProfile,
        on_delete=models.PROTECT,
        related_name="cooperative_memberships",
    )
    cooperative = models.ForeignKey(
        Cooperative,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cooperative__name", "farmer__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["farmer", "cooperative"],
                name="unique_farmer_cooperative_membership",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.farmer_id
            and self.cooperative_id
            and CooperativeMembership.objects.filter(
                farmer=self.farmer,
                cooperative=self.cooperative,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                "A farmer can only have one membership in each cooperative."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.farmer} -> {self.cooperative}"


class CooperativeStaffMembership(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_FIELD_AGENT = "field_agent"
    ROLE_RECORDS_OFFICER = "records_officer"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_FIELD_AGENT, "Field Agent"),
        (ROLE_RECORDS_OFFICER, "Records Officer"),
        (ROLE_VIEWER, "Viewer"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cooperative_staff_memberships",
    )
    cooperative = models.ForeignKey(
        Cooperative,
        on_delete=models.PROTECT,
        related_name="staff_memberships",
    )
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default=ROLE_VIEWER,
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cooperative__name", "user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "cooperative"],
                name="unique_user_cooperative_staff_membership",
            )
        ]

    def clean(self):
        super().clean()
        if (
            self.user_id
            and self.cooperative_id
            and CooperativeStaffMembership.objects.filter(
                user=self.user,
                cooperative=self.cooperative,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                "A user can only be assigned once to each cooperative staff membership."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} -> {self.cooperative} ({self.role})"
