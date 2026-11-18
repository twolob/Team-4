
import secrets
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Value
from django.db.models.functions import Length, Trim
from django.utils import timezone

from apps.cooperatives.models import Cooperative
from apps.farms.models import HarvestBatch


class StorageLocation(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cooperative = models.ForeignKey(
        Cooperative,
        on_delete=models.PROTECT,
        related_name="storage_locations",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=32)
    location_description = models.TextField(blank=True, default="")
    community = models.CharField(max_length=80, blank=True, default="")
    district = models.CharField(max_length=80, blank=True, default="")
    county = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cooperative__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["cooperative", "code"],
                name="unique_storage_location_code_per_cooperative",
            ),
            models.CheckConstraint(
                condition=models.Q(code__isnull=False) & ~models.Q(code=""),
                name="storagelocation_code_not_blank",
            ),
            models.CheckConstraint(
                condition=models.Q(name__isnull=False) & ~models.Q(name=""),
                name="storagelocation_name_not_blank",
            ),
        ]

    def clean(self):
        super().clean()

        if not self.code or not self.code.strip():
            raise ValidationError({"code": "Location code is required."})

        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Location name is required."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.cooperative.name} - {self.name} ({self.code})"


class CoopIntake(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    harvest_batch = models.ForeignKey(
        HarvestBatch,
        on_delete=models.PROTECT,
        related_name="coop_intakes",
    )
    cooperative = models.ForeignKey(
        Cooperative,
        on_delete=models.PROTECT,
        related_name="coop_intakes",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="coop_intakes",
    )
    received_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    received_unit = models.CharField(max_length=32)
    intake_date = models.DateTimeField()
    notes = models.TextField(blank=True, default="")

    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="coop_intakes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-intake_date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(received_quantity__gt=0),
                name="coopintake_received_quantity_positive",
            ),
        ]

    def clean(self):
        super().clean()

        if self.intake_date and self.intake_date > timezone.now():
            raise ValidationError(
                {"intake_date": "Intake date cannot be in the future."}
            )

        if self.received_quantity is None or self.received_quantity <= 0:
            raise ValidationError(
                {"received_quantity": "Quantity must be greater than zero."}
            )

        if not self.received_unit or not self.received_unit.strip():
            raise ValidationError({"received_unit": "Unit is required."})

        if self.storage_location_id is not None and self.cooperative_id is not None:
            if self.storage_location.cooperative_id != self.cooperative_id:
                raise ValidationError(
                    {
                        "storage_location": "Storage location must belong to the cooperative."
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Intake {self.harvest_batch.batch_code} ({self.received_quantity} {self.received_unit})"

class TransferRecord(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_DISPUTED = "disputed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DISPUTED, "Disputed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cooperative = models.ForeignKey(
        Cooperative,
        on_delete=models.PROTECT,
        related_name="transfer_records",
    )
    source_storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="outgoing_transfers",
    )
    destination_storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="incoming_transfers",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="transfer_requests",
    )
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfer_approvals",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    transfer_reference = models.CharField(
        max_length=64,
        blank=True,
        null=True,
    )
    notes = models.TextField(blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-requested_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cooperative", "transfer_reference"],
                name="transferrecord_reference_unique_per_cooperative",
                condition=models.Q(transfer_reference__isnull=False) & ~models.Q(transfer_reference=""),
            ),
        ]

    def clean(self):
        super().clean()

        if self.source_storage_location_id == self.destination_storage_location_id:
            raise ValidationError(
                {"destination_location": "Transfer source and destination must differ."}
            )

        if self.source_storage_location_id is not None and self.destination_storage_location_id is not None:
            if self.source_storage_location.cooperative_id != self.destination_storage_location.cooperative_id:
                raise ValidationError(
                    {"destination_location": "Source and destination must belong to the same cooperative."}
                )
            if self.source_storage_location.cooperative_id != self.cooperative_id:
                raise ValidationError(
                    {"source_storage_location": "Source location must belong to the transfer cooperative."}
                )
            if self.destination_storage_location.cooperative_id != self.cooperative_id:
                raise ValidationError(
                    {"destination_storage_location": "Destination location must belong to the transfer cooperative."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transfer_reference or self.id} ({self.source_storage_location.code} -> {self.destination_storage_location.code})"


class TransferLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer_record = models.ForeignKey(
        TransferRecord,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    harvest_batch = models.ForeignKey(
        HarvestBatch,
        on_delete=models.PROTECT,
        related_name="transfer_lines",
    )
    expected_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    expected_unit = models.CharField(max_length=32)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["transfer_record", "harvest_batch"]
        constraints = [
            models.UniqueConstraint(
                fields=["transfer_record", "harvest_batch"],
                name="transferline_per_batch_per_transfer",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_quantity__gt=0),
                name="transferline_expected_quantity_positive",
            ),
        ]

    def clean(self):
        super().clean()

        if self.expected_quantity is None or self.expected_quantity <= 0:
            raise ValidationError({"expected_quantity": "Quantity must be greater than zero."})

        if not self.expected_unit or not self.expected_unit.strip():
            raise ValidationError({"expected_unit": "Unit is required."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.expected_quantity} {self.expected_unit} - {self.harvest_batch.batch_code}"


class StockMovement(models.Model):
    MOVEMENT_INBOUND_INTAKE = "inbound_intake"
    MOVEMENT_DISPATCH = "transfer_dispatch"
    MOVEMENT_RECEIPT = "transfer_receipt"
    MOVEMENT_WAREHOUSE_LOSS = "warehouse_loss"
    MOVEMENT_TRANSIT_LOSS = "transit_loss"
    MOVEMENT_CORRECTION = "correction"
    MOVEMENT_REVERSAL = "reversal"
    MOVEMENT_CHOICES = [
        (MOVEMENT_INBOUND_INTAKE, "Inbound Intake"),
        (MOVEMENT_DISPATCH, "Transfer Dispatch"),
        (MOVEMENT_RECEIPT, "Transfer Receipt"),
        (MOVEMENT_WAREHOUSE_LOSS, "Warehouse Loss"),
        (MOVEMENT_TRANSIT_LOSS, "Transit Loss"),
        (MOVEMENT_CORRECTION, "Correction"),
        (MOVEMENT_REVERSAL, "Reversal"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    movement_type = models.CharField(
        max_length=24,
        choices=MOVEMENT_CHOICES,
    )
    coop_intake = models.OneToOneField(
        "CoopIntake",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movement",
    )
    transfer_line = models.ForeignKey(
        "TransferLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    loss_record = models.OneToOneField(
        "LossRecord",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movement",
    )
    original_movement = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal_movements",
    )
    source_storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="outgoing_movements",
    )
    destination_storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_movements",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=32)
    occurred_at = models.DateTimeField()
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="stockmovement_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    movement_type__in=[
                        "inbound_intake",
                        "transfer_dispatch",
                        "transfer_receipt",
                        "warehouse_loss",
                        "transit_loss",
                        "correction",
                        "reversal",
                    ]
                ),
                name="stockmovement_movement_type_valid",
            ),
        ]

    def clean(self):
        super().clean()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

        if not self.unit or not self.unit.strip():
            raise ValidationError({"unit": "Unit is required."})

        if self.occurred_at and self.occurred_at > timezone.now():
            raise ValidationError(
                {"occurred_at": "Movement date cannot be in the future."}
            )

        # Validate the complete approved movement relationship matrix. Each
        # movement type requires its own relationship fields and must not carry
        # unrelated relationship fields.
        if self.movement_type == self.MOVEMENT_INBOUND_INTAKE:
            if self.coop_intake_id is None:
                raise ValidationError({"coop_intake": "Inbound intake must be linked to a coop intake."})
            if self.destination_storage_location_id is None:
                raise ValidationError({"destination_storage_location": "Inbound intake must have a destination storage location."})
            if self.source_storage_location_id is not None:
                raise ValidationError({"source_storage_location": "Inbound intake must not have a source storage location."})
            if self.transfer_line_id is not None:
                raise ValidationError({"transfer_line": "Inbound intake must not have a transfer line."})
            if self.loss_record_id is not None:
                raise ValidationError({"loss_record": "Inbound intake must not have a loss record."})
            if self.original_movement_id is not None:
                raise ValidationError({"original_movement": "Inbound intake must not reference an original movement."})

        elif self.movement_type == self.MOVEMENT_DISPATCH:
            if self.transfer_line_id is None:
                raise ValidationError({"transfer_line": "Transfer dispatch must be linked to a transfer line."})
            if self.source_storage_location_id is None:
                raise ValidationError({"source_storage_location": "Transfer dispatch must have a source storage location."})
            if self.destination_storage_location_id is not None:
                raise ValidationError({"destination_storage_location": "Transfer dispatch must not have a destination storage location."})
            if self.coop_intake_id is not None:
                raise ValidationError({"coop_intake": "Transfer dispatch must not have a coop intake."})
            if self.loss_record_id is not None:
                raise ValidationError({"loss_record": "Transfer dispatch must not have a loss record."})
            if self.original_movement_id is not None:
                raise ValidationError({"original_movement": "Transfer dispatch must not reference an original movement."})

        elif self.movement_type == self.MOVEMENT_RECEIPT:
            if self.transfer_line_id is None:
                raise ValidationError({"transfer_line": "Transfer receipt must be linked to a transfer line."})
            if self.destination_storage_location_id is None:
                raise ValidationError({"destination_storage_location": "Transfer receipt must have a destination storage location."})
            if self.source_storage_location_id is not None:
                raise ValidationError({"source_storage_location": "Transfer receipt must not have a source storage location."})
            if self.coop_intake_id is not None:
                raise ValidationError({"coop_intake": "Transfer receipt must not have a coop intake."})
            if self.loss_record_id is not None:
                raise ValidationError({"loss_record": "Transfer receipt must not have a loss record."})
            if self.original_movement_id is not None:
                raise ValidationError({"original_movement": "Transfer receipt must not reference an original movement."})

        elif self.movement_type == self.MOVEMENT_WAREHOUSE_LOSS:
            if self.loss_record_id is None:
                raise ValidationError({"loss_record": "Warehouse loss must be linked to a loss record."})
            if self.source_storage_location_id is None:
                raise ValidationError({"source_storage_location": "Warehouse loss must have a source storage location."})
            if self.destination_storage_location_id is not None:
                raise ValidationError({"destination_storage_location": "Warehouse loss must not have a destination storage location."})
            if self.coop_intake_id is not None:
                raise ValidationError({"coop_intake": "Warehouse loss must not have a coop intake."})
            if self.transfer_line_id is not None:
                raise ValidationError({"transfer_line": "Warehouse loss must not have a transfer line."})
            if self.original_movement_id is not None:
                raise ValidationError({"original_movement": "Warehouse loss must not reference an original movement."})

        elif self.movement_type == self.MOVEMENT_TRANSIT_LOSS:
            if self.loss_record_id is None:
                raise ValidationError({"loss_record": "Transit loss must be linked to a loss record."})
            if self.transfer_line_id is None:
                raise ValidationError({"transfer_line": "Transit loss must be linked to a transfer line."})
            if self.source_storage_location_id is not None:
                raise ValidationError({"source_storage_location": "Transit loss must not have a source storage location."})
            if self.destination_storage_location_id is not None:
                raise ValidationError({"destination_storage_location": "Transit loss must not have a destination storage location."})
            if self.coop_intake_id is not None:
                raise ValidationError({"coop_intake": "Transit loss must not have a coop intake."})
            if self.original_movement_id is not None:
                raise ValidationError({"original_movement": "Transit loss must not reference an original movement."})

        elif self.movement_type in {self.MOVEMENT_CORRECTION, self.MOVEMENT_REVERSAL}:
            if self.original_movement_id is None:
                raise ValidationError({"original_movement": "Corrections and reversals must reference an original movement."})
            if self.coop_intake_id is not None:
                raise ValidationError({"coop_intake": "Corrections and reversals must not have a coop intake."})
            if self.transfer_line_id is not None:
                raise ValidationError({"transfer_line": "Corrections and reversals must not have a transfer line."})
            if self.loss_record_id is not None:
                raise ValidationError({"loss_record": "Corrections and reversals must not have a loss record."})
            if self.source_storage_location_id is not None:
                raise ValidationError({"source_storage_location": "Corrections and reversals must not have a source storage location."})
            if self.destination_storage_location_id is not None:
                raise ValidationError({"destination_storage_location": "Corrections and reversals must not have a destination storage location."})

    def save(self, *args, **kwargs):
        # Model-level immutability protection: persisted StockMovement records
        # cannot be modified. New compensating movements (corrections/reversals)
        # are separate new records and are allowed.
        if not self._state.adding:
            raise ValidationError("StockMovement records cannot be modified after saving.")
        # A newly constructed instance must not overwrite an existing movement
        # by reusing its UUID.
        if self.pk is not None and StockMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError("StockMovement records cannot be modified after saving.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Model-level immutability protection: persisted StockMovement records
        # cannot be deleted. New compensating movements (corrections/reversals)
        # are the approved correction mechanism; existing persisted records are immutable.
        if not self._state.adding:
            raise ValidationError("StockMovement records cannot be deleted after saving.")
        # A newly constructed instance must not delete an existing movement
        # by reusing its UUID.
        if self.pk is not None and StockMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError("StockMovement records cannot be deleted after saving.")
        super().delete(*args, **kwargs)


LOSS_TYPE_WAREHOUSE = "warehouse_loss"
LOSS_TYPE_TRANSIT = "transit_loss"
LOSS_TYPE_CHOICES = [
    (LOSS_TYPE_WAREHOUSE, "Warehouse Loss"),
    (LOSS_TYPE_TRANSIT, "Transit Loss"),
]

REASON_CHOICES = [
    ("damage", "Damage"),
    ("spoilage", "Spoilage"),
    ("contamination", "Contamination"),
    ("theft", "Theft"),
    ("handling", "Handling"),
    ("transit_damage", "Transit Damage"),
    ("other", "Other"),
    ("unexplained_discrepancy", "Unexplained Discrepancy"),

]


class LossRecord(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    harvest_batch = models.ForeignKey(
        HarvestBatch,
        on_delete=models.PROTECT,
        related_name="loss_records",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="loss_records",
    )
    transfer_line = models.ForeignKey(
        "TransferLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="loss_records",
    )
    loss_type = models.CharField(
        max_length=24,
        choices=LOSS_TYPE_CHOICES,
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit = models.CharField(max_length=32)
    reason_category = models.CharField(
        max_length=32,
        choices=REASON_CHOICES,
    )
    notes = models.TextField()
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="loss_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()

        if self.quantity is None or self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

        if not self.unit or not self.unit.strip():
            raise ValidationError({"unit": "Unit is required."})

        if self.loss_type not in {LOSS_TYPE_WAREHOUSE, LOSS_TYPE_TRANSIT}:
            raise ValidationError(
                {"loss_type": "Loss type must be warehouse_loss or transit_loss."}
            )

        if self.loss_type == LOSS_TYPE_WAREHOUSE and not self.storage_location:
            raise ValidationError(
                {"storage_location": "Warehouse loss must have a storage location."}
            )

        if self.loss_type == LOSS_TYPE_TRANSIT and not self.transfer_line:
            raise ValidationError(
                {"transfer_line": "Transit loss must have a transfer line."}
            )

        if self.loss_type == LOSS_TYPE_WAREHOUSE and self.transfer_line_id is not None:
            raise ValidationError(
                {"transfer_line": "Warehouse loss must not have a transfer line."}
            )

        if self.loss_type == LOSS_TYPE_TRANSIT and self.storage_location_id is not None:
            raise ValidationError(
                {"storage_location": "Transit loss must not have a storage location."}
            )

        if self.loss_type == LOSS_TYPE_TRANSIT and self.transfer_line.harvest_batch_id != self.harvest_batch_id:
            raise ValidationError(
                {"transfer_line": "Transit loss transfer line must match the loss record harvest batch."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Loss at {self.harvest_batch.batch_code} ({self.loss_type}) ({self.quantity} {self.unit})"
