import os
import secrets
import uuid
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError, models, transaction
from django.db.models import Value
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan
from django.utils import timezone
from PIL import Image

MAX_QUALITY_INSPECTION_PHOTO_SIZE = 8 * 1024 * 1024
VALID_QUALITY_INSPECTION_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class PrivateInspectionStorage(FileSystemStorage):
    def __init__(self, location=None, base_url=None, *args, **kwargs):
        resolved_location = location or getattr(settings, "PRIVATE_MEDIA_ROOT", None)
        if resolved_location is None:
            raise ValueError(
                "PRIVATE_MEDIA_ROOT must be configured before using PrivateInspectionStorage."
            )

        super().__init__(
            location=str(resolved_location),
            base_url="",
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
            *args,
            **kwargs,
        )

    def url(self, name):
        raise ValueError(
            "Inspection photos are stored privately and do not have public URLs."
        )

    def generate_filename(self, name):
        original_name = os.path.basename(name)
        stem, extension = os.path.splitext(original_name)
        normalized_extension = extension.lower()
        if normalized_extension not in VALID_QUALITY_INSPECTION_PHOTO_EXTENSIONS:
            normalized_extension = ".jpg"

        safe_stem = "".join(
            character
            for character in stem
            if character.isalnum() or character in {"-", "_"}
        )
        if not safe_stem:
            safe_stem = "inspection"

        return os.path.join(
            "quality_inspections",
            f"{uuid.uuid4().hex}_{safe_stem}{normalized_extension}",
        )


def validate_inspection_photo(file):
    if file is None:
        raise ValidationError("A photo is required.")

    if file.size is None or file.size > MAX_QUALITY_INSPECTION_PHOTO_SIZE:
        raise ValidationError("Photo must be 8 MB or smaller.")

    extension = os.path.splitext(file.name or "")[1].lower()
    if extension not in VALID_QUALITY_INSPECTION_PHOTO_EXTENSIONS:
        raise ValidationError("Photo must be a JPG, JPEG, PNG, or WEBP image.")

    extension_to_format = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
    }
    expected_format = extension_to_format.get(extension)

    file_position = None
    try:
        file_position = file.tell()
        file.seek(0)

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file) as image:
                image.verify()

        file.seek(0)

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file) as image:
                image.load()
                actual_format = (image.format or "").upper()
                if actual_format != expected_format:
                    raise ValidationError(
                        "Uploaded image format does not match the file extension."
                    )
    except (
        Image.UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombWarning,
    ):
        raise ValidationError("Uploaded file is not a valid image.")
    except Image.DecompressionBombError:
        raise ValidationError("Uploaded image is too large to process safely.")
    finally:
        try:
            if file_position is not None:
                file.seek(file_position)
            else:
                file.seek(0)
        except (AttributeError, ValueError):
            try:
                file.seek(0)
            except Exception:
                pass


class Farm(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(
        "farmers.FarmerProfile",
        on_delete=models.PROTECT,
        related_name="farms",
    )
    name = models.CharField(max_length=150)
    location_description = models.CharField(max_length=255, blank=True, default="")
    community = models.CharField(max_length=120, blank=True, default="")
    district = models.CharField(max_length=120, blank=True, default="")
    county = models.CharField(max_length=120, blank=True, default="")
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
    )
    total_area_hectares = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "created_at"]

    def clean(self):
        super().clean()
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None

        if has_latitude != has_longitude:
            raise ValidationError(
                {
                    "latitude": "Latitude and longitude must be supplied together.",
                    "longitude": "Latitude and longitude must be supplied together.",
                }
            )

        if has_latitude:
            lat_value = float(self.latitude)
            if not -90 <= lat_value <= 90:
                raise ValidationError(
                    {"latitude": "Latitude must be between -90 and 90."}
                )

        if has_longitude:
            lon_value = float(self.longitude)
            if not -180 <= lon_value <= 180:
                raise ValidationError(
                    {"longitude": "Longitude must be between -180 and 180."}
                )

        if self.total_area_hectares is not None and self.total_area_hectares <= 0:
            raise ValidationError(
                {"total_area_hectares": "Area must be greater than zero."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Plot(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="plots")
    name = models.CharField(max_length=150)
    plot_code = models.CharField(max_length=32)
    area_hectares = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["farm", "plot_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["farm", "plot_code"],
                name="unique_plot_code_per_farm",
            )
        ]

    def clean(self):
        super().clean()
        has_latitude = self.latitude is not None
        has_longitude = self.longitude is not None

        if has_latitude != has_longitude:
            raise ValidationError(
                {
                    "latitude": "Latitude and longitude must be supplied together.",
                    "longitude": "Latitude and longitude must be supplied together.",
                }
            )

        if has_latitude:
            lat_value = float(self.latitude)
            if not -90 <= lat_value <= 90:
                raise ValidationError(
                    {"latitude": "Latitude must be between -90 and 90."}
                )

        if has_longitude:
            lon_value = float(self.longitude)
            if not -180 <= lon_value <= 180:
                raise ValidationError(
                    {"longitude": "Longitude must be between -180 and 180."}
                )

        if self.area_hectares is not None and self.area_hectares <= 0:
            raise ValidationError({"area_hectares": "Area must be greater than zero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.farm.name}: {self.plot_code}"


class CropSeason(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plot = models.ForeignKey(
        Plot, on_delete=models.PROTECT, related_name="crop_seasons"
    )
    season_name = models.CharField(max_length=120)
    crop_type = models.CharField(max_length=80)
    planned_planting_date = models.DateField()
    actual_planting_date = models.DateField(null=True, blank=True)
    expected_harvest_date = models.DateField(null=True, blank=True)
    actual_harvest_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["plot", "planned_planting_date", "season_name"]

    @staticmethod
    def _effective_start_date_for(season):
        return season.actual_planting_date or season.planned_planting_date

    @staticmethod
    def _effective_end_date_for(season):
        return season.actual_harvest_date or season.expected_harvest_date

    def _has_overlap_with(self, other):
        if (
            self.status == self.STATUS_CANCELLED
            or other.status == other.STATUS_CANCELLED
        ):
            return False

        self_start = self._effective_start_date_for(self)
        other_start = self._effective_start_date_for(other)
        self_end = self._effective_end_date_for(self)
        other_end = self._effective_end_date_for(other)

        return (other_end is None or self_start <= other_end) and (
            self_end is None or other_start <= self_end
        )

    def clean(self):
        super().clean()

        if (
            self.expected_harvest_date
            and self.expected_harvest_date < self.planned_planting_date
        ):
            raise ValidationError(
                {
                    "expected_harvest_date": "Expected harvest date cannot precede planned planting date."
                }
            )

        if (
            self.actual_planting_date
            and self.actual_harvest_date
            and self.actual_harvest_date < self.actual_planting_date
        ):
            raise ValidationError(
                {
                    "actual_harvest_date": "Actual harvest date cannot precede actual planting date."
                }
            )

        if self.status != self.STATUS_CANCELLED:
            overlapping = CropSeason.objects.filter(plot=self.plot).exclude(pk=self.pk)
            for other in overlapping:
                if other.status == self.STATUS_CANCELLED:
                    continue
                if self._has_overlap_with(other):
                    raise ValidationError(
                        {
                            "plot": "Non-cancelled crop seasons on the same plot cannot overlap."
                        }
                    )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            plot_ids = {self.plot_id}
            if self.pk:
                existing_plot_id = (
                    CropSeason.objects.filter(pk=self.pk)
                    .values_list("plot_id", flat=True)
                    .first()
                )
                if existing_plot_id is not None and existing_plot_id != self.plot_id:
                    plot_ids.add(existing_plot_id)

            ordered_plot_ids = sorted(
                plot_id for plot_id in plot_ids if plot_id is not None
            )
            locked_plots = []
            if ordered_plot_ids:
                locked_plots = list(
                    Plot.objects.filter(pk__in=ordered_plot_ids)
                    .select_for_update()
                    .order_by("pk")
                )

            self.full_clean()
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.season_name} ({self.crop_type})"


class FarmActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crop_season = models.ForeignKey(
        CropSeason,
        on_delete=models.PROTECT,
        related_name="activities",
    )
    activity_type = models.CharField(max_length=80)
    activity_date = models.DateField()
    description = models.TextField()
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farm_activities",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-activity_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["crop_season", "activity_date"],
                name="farmactivity_season_date_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("activity_type")), Value(0)),
                name="farmactivity_activity_type_not_blank",
            )
        ]

    def clean(self):
        super().clean()

        if not self.activity_type or not self.activity_type.strip():
            raise ValidationError({"activity_type": "Activity type is required."})

        if self.activity_date and self.activity_date > timezone.now().date():
            raise ValidationError(
                {"activity_date": "Activity date cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.activity_type} ({self.activity_date})"


class InputRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crop_season = models.ForeignKey(
        CropSeason,
        on_delete=models.PROTECT,
        related_name="input_records",
    )
    input_type = models.CharField(max_length=80)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=32)
    application_date = models.DateField()
    applied_by = models.CharField(max_length=150, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="input_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-application_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["crop_season", "application_date"],
                name="inputrecord_season_date_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="inputrecord_quantity_positive",
            ),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("input_type")), Value(0)),
                name="inputrecord_input_type_not_blank",
            ),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("unit")), Value(0)),
                name="inputrecord_unit_not_blank",
            ),
        ]

    def clean(self):
        super().clean()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

        if not self.input_type or not self.input_type.strip():
            raise ValidationError({"input_type": "Input type is required."})

        if not self.unit or not self.unit.strip():
            raise ValidationError({"unit": "Unit is required."})

        if self.application_date and self.application_date > timezone.now().date():
            raise ValidationError(
                {"application_date": "Application date cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.input_type} ({self.quantity} {self.unit})"


class HarvestBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crop_season = models.ForeignKey(
        CropSeason,
        on_delete=models.PROTECT,
        related_name="harvest_batches",
    )
    batch_code = models.CharField(max_length=64, unique=True, editable=False)
    harvest_date = models.DateField()
    farmer_reported_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    farmer_reported_unit = models.CharField(max_length=32)
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="harvest_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-harvest_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["crop_season", "harvest_date"],
                name="harvestbatch_season_date_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(farmer_reported_quantity__gt=0),
                name="harvestbatch_quantity_positive",
            ),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("farmer_reported_unit")), Value(0)),
                name="harvestbatch_unit_not_blank",
            ),
        ]

    @staticmethod
    def _generate_batch_code():
        return f"FP-{secrets.token_hex(6).upper()}"

    @staticmethod
    def _is_batch_code_unique_collision(exc):
        details = " ".join(str(arg) for arg in getattr(exc, "args", [])).lower()
        cause = getattr(exc, "__cause__", None)
        if cause is not None:
            details += " " + str(cause).lower()

        if "batch_code" not in details:
            return False

        has_unique_constraint_marker = (
            "unique constraint" in details
            or "duplicate key" in details
            or "already exists" in details
        )
        return has_unique_constraint_marker

    def clean(self):
        super().clean()

        if self.pk:
            existing_code = (
                self.__class__.objects.filter(pk=self.pk)
                .values_list("batch_code", flat=True)
                .first()
            )
            if existing_code is not None and self.batch_code != existing_code:
                raise ValidationError(
                    {"batch_code": "Batch code cannot be changed after creation."}
                )

        if self.farmer_reported_quantity is None or self.farmer_reported_quantity <= 0:
            raise ValidationError(
                {"farmer_reported_quantity": "Quantity must be greater than zero."}
            )

        if not self.farmer_reported_unit or not self.farmer_reported_unit.strip():
            raise ValidationError({"farmer_reported_unit": "Unit is required."})

        if self.harvest_date and self.harvest_date > timezone.now().date():
            raise ValidationError(
                {"harvest_date": "Harvest date cannot be in the future."}
            )

        if (
            self.crop_season_id is not None
            and self.crop_season is not None
            and self.crop_season.actual_planting_date is not None
            and self.harvest_date < self.crop_season.actual_planting_date
        ):
            raise ValidationError(
                {
                    "harvest_date": "Harvest date cannot precede the actual planting date."
                }
            )

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        if not is_new:
            existing_code = (
                self.__class__.objects.filter(pk=self.pk)
                .values_list("batch_code", flat=True)
                .first()
            )
            if existing_code is not None and self.batch_code != existing_code:
                raise ValidationError(
                    {"batch_code": "Batch code cannot be changed after creation."}
                )

            self.full_clean()
            return super().save(*args, **kwargs)

        self.batch_code = self._generate_batch_code()
        for _ in range(8):
            try:
                with transaction.atomic():
                    self.full_clean(exclude={"batch_code"})
                    return super().save(*args, **kwargs)
            except IntegrityError as exc:
                if not self._is_batch_code_unique_collision(exc):
                    raise
                self.batch_code = self._generate_batch_code()
        raise IntegrityError("Unable to generate a unique HarvestBatch batch code.")

    def __str__(self):
        return f"{self.batch_code} ({self.farmer_reported_quantity} {self.farmer_reported_unit})"


class QualityInspection(models.Model):
    REVIEW_STATUS_RECORDED = "recorded"
    REVIEW_STATUS_REVIEW_REQUIRED = "review_required"
    REVIEW_STATUS_REVIEWED = "reviewed"
    REVIEW_STATUS_CHOICES = [
        (REVIEW_STATUS_RECORDED, "Recorded"),
        (REVIEW_STATUS_REVIEW_REQUIRED, "Review required"),
        (REVIEW_STATUS_REVIEWED, "Reviewed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    harvest_batch = models.ForeignKey(
        HarvestBatch,
        on_delete=models.PROTECT,
        related_name="inspections",
    )
    inspection_date = models.DateTimeField()
    inspector = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="quality_inspections",
    )
    review_status = models.CharField(
        max_length=24,
        choices=REVIEW_STATUS_CHOICES,
        default=REVIEW_STATUS_RECORDED,
    )
    observation_summary = models.TextField()
    notes = models.TextField(blank=True, default="")
    photo = models.ImageField(
        upload_to="quality_inspections/",
        storage=PrivateInspectionStorage(),
        validators=[validate_inspection_photo],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-inspection_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["harvest_batch", "inspection_date"],
                name="qi_batch_date_idx",
            )
        ]

    def clean(self):
        super().clean()

        if not self.photo:
            raise ValidationError({"photo": "Photo is required."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Inspection for {self.harvest_batch.batch_code} on {self.inspection_date}"
        )


class ExpenseRecord(models.Model):
    CURRENCY_LRD = "LRD"
    CURRENCY_USD = "USD"
    CURRENCY_CHOICES = [
        (CURRENCY_LRD, "LRD"),
        (CURRENCY_USD, "USD"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(
        Farm,
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    crop_season = models.ForeignKey(
        CropSeason,
        on_delete=models.PROTECT,
        related_name="expenses",
        null=True,
        blank=True,
    )
    expense_type = models.CharField(max_length=80)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    expense_date = models.DateField()
    vendor_name = models.CharField(max_length=150, blank=True, default="")
    description = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expense_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-created_at"]
        indexes = [
            models.Index(
                fields=["farm", "expense_date"],
                name="expense_farm_date_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="expense_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(currency__in=["LRD", "USD"]),
                name="expense_currency_valid",
            ),
            models.CheckConstraint(
                condition=GreaterThan(Length(Trim("expense_type")), Value(0)),
                name="expense_type_not_blank",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.crop_season_id is not None
            and self.crop_season.plot.farm_id != self.farm_id
        ):
            raise ValidationError(
                {"crop_season": "Crop season must belong to the selected farm."}
            )

        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than zero."})

        if self.currency not in {self.CURRENCY_LRD, self.CURRENCY_USD}:
            raise ValidationError({"currency": "Currency must be LRD or USD."})

        if not self.expense_type or not self.expense_type.strip():
            raise ValidationError({"expense_type": "Expense type is required."})

        if self.expense_date and self.expense_date > timezone.now().date():
            raise ValidationError(
                {"expense_date": "Expense date cannot be in the future."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.expense_type} ({self.amount} {self.currency})"
