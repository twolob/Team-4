import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, models, transaction
from django.db.models import Q


class FarmerIDSequence(models.Model):
    key = models.CharField(max_length=32, unique=True, default="farmer_profile")
    last_value = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"{self.key}:{self.last_value}"


class FarmerProfile(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    farmer_id = models.CharField(max_length=32, unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="farmer_profile",
    )
    full_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name", "farmer_id"]

    @staticmethod
    def is_lock_contention_error(exc):
        if not isinstance(exc, OperationalError):
            return False
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "database is locked",
                "database table is locked",
                "database is busy",
                "could not obtain lock",
                "deadlock",
                "lock timeout",
                "serialization failure",
            )
        )

    @staticmethod
    def is_farmer_id_conflict(exc):
        message = str(exc).lower()
        return "farmer_id" in message and (
            "unique" in message or "duplicate" in message or "constraint" in message
        )

    @classmethod
    def allocate_farmer_id(cls):
        for _ in range(100):
            try:
                with transaction.atomic():
                    (
                        sequence,
                        _,
                    ) = FarmerIDSequence.objects.select_for_update().get_or_create(
                        key="farmer_profile",
                        defaults={"last_value": 0},
                    )
                    sequence.last_value += 1
                    sequence.save(update_fields=["last_value"])
                    return f"FP-{sequence.last_value:06d}"
            except IntegrityError as exc:
                if cls.is_farmer_id_conflict(exc):
                    continue
                raise
            except OperationalError as exc:
                if cls.is_lock_contention_error(exc):
                    continue
                raise
        raise RuntimeError("Unable to allocate a unique farmer ID.")

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.farmer_id and self.farmer_id.startswith("FP-"):
                raise ValidationError(
                    "FP- IDs are reserved for system-generated farmer IDs."
                )

            if not self.farmer_id:
                for _ in range(50):
                    self.farmer_id = self.allocate_farmer_id()
                    try:
                        with transaction.atomic():
                            return super().save(*args, **kwargs)
                    except IntegrityError as exc:
                        if not self.is_farmer_id_conflict(exc):
                            raise
                    except OperationalError as exc:
                        if not self.is_lock_contention_error(exc):
                            raise
                raise RuntimeError("Unable to allocate a unique farmer ID.")

            return super().save(*args, **kwargs)

        existing_farmer_id = (
            FarmerProfile.objects.filter(pk=self.pk)
            .values_list("farmer_id", flat=True)
            .first()
        )

        if self.farmer_id in (None, ""):
            raise ValidationError("Farmer ID cannot be cleared.")

        if existing_farmer_id is not None and self.farmer_id != existing_farmer_id:
            raise ValidationError("Farmer ID is immutable once assigned.")

        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.farmer_id})"


class FarmerContact(models.Model):
    CONTACT_TYPE_PERSONAL = "personal"
    CONTACT_TYPE_SHARED = "shared"
    CONTACT_TYPE_CHOICES = [
        (CONTACT_TYPE_PERSONAL, "Personal"),
        (CONTACT_TYPE_SHARED, "Shared"),
    ]

    farmer = models.ForeignKey(
        FarmerProfile,
        on_delete=models.PROTECT,
        related_name="contacts",
    )
    phone_number = models.CharField(max_length=32)
    contact_type = models.CharField(
        max_length=16,
        choices=CONTACT_TYPE_CHOICES,
        default=CONTACT_TYPE_PERSONAL,
    )
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    contact_owner_name = models.CharField(max_length=255, blank=True, default="")
    relationship_to_farmer = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def normalize_phone_number(phone_number, country_code=None):
        if phone_number is None:
            return ""

        value = str(phone_number).strip()
        if not value:
            return ""

        for char in value:
            if char.isalpha():
                raise ValidationError(
                    "Phone number contains invalid alphabetic characters."
                )
            if char in {"@", "#", "*", "_", "/", "\\"}:
                raise ValidationError("Phone number contains unsupported characters.")

        compact = re.sub(r"\s+", "", value)
        if not compact:
            return ""

        if compact.startswith("00"):
            candidate = compact[2:]
            if not candidate or not re.fullmatch(r"[0-9().-]*", candidate):
                raise ValidationError("Invalid international phone number format.")
            digits = re.sub(r"\D", "", candidate)
            if not digits:
                raise ValidationError("International phone number is missing digits.")
            return f"+{digits}"

        if compact.startswith("+"):
            candidate = compact[1:]
            if not candidate or not re.fullmatch(r"[0-9().-]*", candidate):
                raise ValidationError("Invalid international phone number format.")
            digits = re.sub(r"\D", "", candidate)
            if not digits:
                raise ValidationError("International phone number is missing digits.")
            return f"+{digits}"

        if not re.fullmatch(r"[0-9().-]*", compact):
            raise ValidationError("Phone number contains unsupported characters.")

        digits = re.sub(r"\D", "", compact)
        if not digits:
            raise ValidationError("Phone number is missing digits.")

        if country_code and str(country_code).upper() in {"LR", "LIBERIA"}:
            local_digits = digits
            if local_digits.startswith("0"):
                local_digits = local_digits[1:]
            if len(local_digits) == 9:
                return f"+231{local_digits}"

        return digits

    class Meta:
        ordering = ["farmer", "phone_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["farmer"],
                condition=Q(is_primary=True),
                name="unique_primary_contact_per_farmer",
            )
        ]

    def clean(self):
        super().clean()
        try:
            normalized = self.normalize_phone_number(self.phone_number)
        except ValidationError as exc:
            raise ValidationError({"phone_number": str(exc)}) from exc

        if not normalized:
            raise ValidationError({"phone_number": "Phone number is required."})
        self.phone_number = normalized

        if self.is_primary and self.contact_type == self.CONTACT_TYPE_SHARED:
            raise ValidationError(
                {"contact_type": "A shared contact cannot be marked as primary."}
            )

        if (
            self.is_primary
            and FarmerContact.objects.filter(
                farmer=self.farmer,
                is_primary=True,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {"is_primary": "Only one primary contact is allowed per farmer."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.farmer.full_name}: {self.phone_number}"
