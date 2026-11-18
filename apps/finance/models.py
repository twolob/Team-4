
import secrets
import uuid

from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Value
from django.db.models.functions import Length, Trim
from django.utils import timezone


class SaleRecord(models.Model):
    CURRENCY_LRD = "LRD"
    CURRENCY_USD = "USD"
    CURRENCY_CHOICES = [
        (CURRENCY_LRD, "LRD"),
        (CURRENCY_USD, "USD"),
    ]

    STATUS_RECORDED = "recorded"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_RECORDED, "Recorded"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cooperative = models.ForeignKey(
        "cooperatives.Cooperative",
        on_delete=models.PROTECT,
        related_name="sale_records",
    )
    harvest_batch = models.ForeignKey(
        "farms.HarvestBatch",
        on_delete=models.PROTECT,
        related_name="sale_records",
    )
    sale_reference = models.CharField(
        max_length=64, unique=True, editable=False, default=""
    )
    buyer_name = models.CharField(max_length=255)
    buyer_phone = models.CharField(max_length=120, blank=True, default="")
    buyer_email = models.EmailField(max_length=254, blank=True, default="")
    sale_date = models.DateField()
    sold_quantity = models.DecimalField(max_digits=14, decimal_places=4)
    sold_unit = models.CharField(max_length=32)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, editable=False)
    exchange_rate_lrd_per_usd = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="sale_records",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_RECORDED,
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sale_date", "-created_at"]

    def clean(self):
        super().clean()

        if self.sold_quantity is None or self.sold_quantity <= 0:
            raise ValidationError({"sold_quantity": "Quantity must be greater than zero."})

        if self.unit_price is None or self.unit_price <= 0:
            raise ValidationError({"unit_price": "Unit price must be greater than zero."})

        if not self.buyer_name or not self.buyer_name.strip():
            raise ValidationError({"buyer_name": "Buyer name is required."})

        if not self.sold_unit or not self.sold_unit.strip():
            raise ValidationError({"sold_unit": "Unit is required."})

        if self.currency not in [self.CURRENCY_LRD, self.CURRENCY_USD]:
            raise ValidationError({"currency": "Currency must be LRD or USD."})

        if self.exchange_rate_lrd_per_usd is not None:
            if self.exchange_rate_lrd_per_usd <= 0:
                raise ValidationError(
                    {"exchange_rate_lrd_per_usd": "Exchange rate must be greater than zero when supplied."}
                )

        if self.sale_date and self.sale_date > timezone.now().date():
            raise ValidationError({"sale_date": "Sale date cannot be in the future."})

        if self.status == self.STATUS_CANCELLED:
            if not self.cancelled_reason or not self.cancelled_reason.strip():
                raise ValidationError({"cancelled_reason": "Cancellation reason is required for cancelled sales."})
            if not self.cancelled_at:
                raise ValidationError({"cancelled_at": "Cancellation timestamp is required for cancelled sales."})

        if self.status == self.STATUS_RECORDED:
            if self.cancelled_reason or self.cancelled_at:
                raise ValidationError(
                    {"status": "Recorded sales must not carry cancellation information."}
                )

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        # Calculate total_amount before full_clean() so that field validation
        # does not reject a missing value. total_amount is backend-controlled,
        # computed from sold_quantity × unit_price with ROUND_HALF_UP.
        expected_total = Decimal(str(self.sold_quantity)) * Decimal(str(self.unit_price))
        self.total_amount = expected_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if is_new and not self.sale_reference:
            self.sale_reference = f"SALE-{secrets.token_hex(6).upper()}"
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.sale_reference} ({self.buyer_name} {self.sold_quantity} {self.sold_unit})"
