import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import AfterValidator, EmailStr, model_validator
from sqlalchemy import JSON, CheckConstraint, Column, String, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.main import SQLModelConfig


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


def normalize_phone(value: str) -> str:
    value = re.sub(r"[\s()-]", "", value)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
        raise ValueError(
            "Use an international phone number, including + and country code"
        )
    return value


PhoneNumber = Annotated[str, AfterValidator(normalize_phone)]


# Shared properties
class UserBase(SQLModel):
    email: EmailStr | None = Field(
        default=None, unique=True, index=True, max_length=255
    )
    phone_number: PhoneNumber | None = Field(
        default=None, unique=True, index=True, max_length=16
    )
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    @model_validator(mode="after")
    def require_identifier(self) -> Self:
        if not self.email and not self.phone_number:
            raise ValueError("An email or phone number is required")
        return self

    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(default_factory=get_datetime_utc)
    farms: list[Farm] = Relationship(back_populates="owner", cascade_delete=True)
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    category: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=50)
    reorder_level: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=4
    )
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    model_config = SQLModelConfig(extra="forbid")
    farm_id: uuid.UUID | None = None


# Properties to receive on item update
class ItemUpdate(SQLModel):
    model_config = SQLModelConfig(extra="forbid")
    farm_id: uuid.UUID | None = None
    category: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=50)
    reorder_level: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=4
    )
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    __table_args__ = (CheckConstraint("quantity >= 0", name="ck_item_quantity"),)
    farm_id: uuid.UUID | None = Field(default=None, foreign_key="farm.id", index=True)
    quantity: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=4)
    updated_at: datetime = Field(default_factory=get_datetime_utc)
    farm: Farm = Relationship(back_populates="items")
    transactions: list[InventoryTransaction] = Relationship(
        back_populates="item", passive_deletes="all"
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(default_factory=get_datetime_utc)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    farm_id: uuid.UUID | None = None
    quantity: Decimal
    updated_at: datetime
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class FarmBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    county: str = Field(min_length=1, max_length=100)
    farm_type: str = Field(min_length=1, max_length=100)
    community: str | None = Field(default=None, max_length=255)


class FarmCreate(FarmBase):
    pass


class Farm(FarmBase, table=True):
    items: list[Item] = Relationship(back_populates="farm", passive_deletes="all")
    expenses: list[FarmExpense] = Relationship(
        back_populates="farm", passive_deletes="all"
    )
    harvests: list[Harvest] = Relationship(back_populates="farm", passive_deletes="all")
    losses: list[LossRecord] = Relationship(
        back_populates="farm", passive_deletes="all"
    )
    reports: list[FarmReport] = Relationship(
        back_populates="farm", passive_deletes="all"
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    owner: User | None = Relationship(back_populates="farms")


class FarmPublic(FarmBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime


class FarmerRegister(SQLModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone_number: PhoneNumber
    password: str = Field(min_length=8, max_length=128)
    farm: FarmCreate
    email: EmailStr | None = None


class FarmerRegistration(SQLModel):
    user: UserPublic
    farm: FarmPublic


class FarmerProfileUpdate(SQLModel):
    full_name: str = Field(min_length=1, max_length=255)


class FarmUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    county: str | None = Field(default=None, min_length=1, max_length=100)
    farm_type: str | None = Field(default=None, min_length=1, max_length=100)
    community: str | None = Field(default=None, max_length=255)


class InventoryTransactionCreate(SQLModel):
    item_id: uuid.UUID
    transaction_type: Literal["IN", "OUT", "ADJUSTMENT"]
    quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    transaction_date: datetime = Field(default_factory=get_datetime_utc, index=True)
    notes: str | None = Field(default=None, max_length=1000)
    idempotency_key: uuid.UUID

    @model_validator(mode="after")
    def validate_quantity(self) -> Self:
        if self.transaction_type != "ADJUSTMENT" and self.quantity <= 0:
            raise ValueError("IN and OUT quantities must be positive")
        if self.transaction_date.tzinfo is None:
            raise ValueError("transaction_date must include a timezone")
        return self


class InventoryTransaction(InventoryTransactionCreate, table=True):
    transaction_type: Literal["IN", "OUT", "ADJUSTMENT"] = Field(
        sa_type=String(20), index=True
    )
    __table_args__ = (
        UniqueConstraint("item_id", "idempotency_key", name="uq_stock_request"),
        CheckConstraint("quantity >= 0", name="ck_stock_quantity"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    item_id: uuid.UUID = Field(foreign_key="item.id", index=True)
    balance_after: Decimal = Field(max_digits=18, decimal_places=4)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    item: Item = Relationship(back_populates="transactions")


class InventoryTransactionPublic(InventoryTransactionCreate):
    id: uuid.UUID
    balance_after: Decimal
    created_at: datetime


class InventoryTransactionsPublic(SQLModel):
    data: list[InventoryTransactionPublic]
    count: int


class FarmExpenseBase(SQLModel):
    farm_id: uuid.UUID = Field(foreign_key="farm.id", index=True)
    category: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Literal["LRD", "USD"] = "LRD"
    expense_date: date = Field(index=True)


class FarmExpenseCreate(FarmExpenseBase):
    pass


class FarmExpenseUpdate(SQLModel):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    currency: Literal["LRD", "USD"] | None = None
    expense_date: date | None = None


class FarmExpense(FarmExpenseBase, table=True):
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_amount"),
        CheckConstraint("currency IN ('LRD', 'USD')", name="ck_expense_currency"),
    )
    currency: Literal["LRD", "USD"] = Field(
        default="LRD", sa_type=String(3), index=True
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    farm: Farm = Relationship(back_populates="expenses")


class FarmExpensePublic(FarmExpenseBase):
    id: uuid.UUID
    created_at: datetime


class FarmExpensesPublic(SQLModel):
    data: list[FarmExpensePublic]
    count: int


class HarvestBase(SQLModel):
    farm_id: uuid.UUID = Field(foreign_key="farm.id", index=True)
    crop_name: str = Field(min_length=1, max_length=100, index=True)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=50)
    harvest_date: date = Field(index=True)
    notes: str | None = Field(default=None, max_length=1000)


class HarvestCreate(HarvestBase):
    pass


class HarvestUpdate(SQLModel):
    crop_name: str | None = Field(
        default=None, min_length=1, max_length=100, index=True
    )
    quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=4
    )
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    harvest_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


class Harvest(HarvestBase, table=True):
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_harvest_quantity"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    farm: Farm = Relationship(back_populates="harvests")
    traceability: list[TraceabilityRecord] = Relationship(
        back_populates="harvest", passive_deletes="all"
    )
    losses: list[LossRecord] = Relationship(
        back_populates="harvest", passive_deletes="all"
    )


class HarvestPublic(HarvestBase):
    id: uuid.UUID
    created_at: datetime


class HarvestsPublic(SQLModel):
    data: list[HarvestPublic]
    count: int


class LossRecordBase(SQLModel):
    farm_id: uuid.UUID = Field(foreign_key="farm.id", index=True)
    harvest_id: uuid.UUID | None = Field(
        default=None, foreign_key="harvest.id", index=True
    )
    loss_type: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=50)
    reason: str | None = Field(default=None, max_length=1000)
    recorded_at: datetime = Field(default_factory=get_datetime_utc, index=True)


class LossRecordCreate(LossRecordBase):
    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        return self


class LossRecordUpdate(SQLModel):
    harvest_id: uuid.UUID | None = Field(
        default=None, foreign_key="harvest.id", index=True
    )
    loss_type: str | None = Field(default=None, min_length=1, max_length=100)
    quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=4
    )
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    reason: str | None = Field(default=None, max_length=1000)
    recorded_at: datetime | None = Field(default=None)


class LossRecord(LossRecordBase, table=True):
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_loss_quantity"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    farm: Farm = Relationship(back_populates="losses")
    harvest: Harvest | None = Relationship(back_populates="losses")


class LossRecordPublic(LossRecordBase):
    id: uuid.UUID


class LossRecordsPublic(SQLModel):
    data: list[LossRecordPublic]
    count: int


class TraceabilityRecordBase(SQLModel):
    harvest_id: uuid.UUID
    origin: str = Field(min_length=1, max_length=255)
    destination: str | None = Field(default=None, max_length=255)
    status: Literal["HARVESTED", "STORED", "IN_TRANSIT", "DELIVERED"]
    recorded_at: datetime = Field(default_factory=get_datetime_utc, index=True)
    event_key: uuid.UUID


class TraceabilityRecordCreate(TraceabilityRecordBase):
    batch_code: str | None = Field(default=None, min_length=1, max_length=100)


class TraceabilityRecord(TraceabilityRecordBase, table=True):
    status: Literal["HARVESTED", "STORED", "IN_TRANSIT", "DELIVERED"] = Field(
        sa_type=String(30), index=True
    )
    __table_args__ = (
        UniqueConstraint("harvest_id", "event_key", name="uq_trace_event"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    harvest_id: uuid.UUID = Field(foreign_key="harvest.id", index=True)
    batch_code: str = Field(index=True, max_length=100)
    harvest: Harvest = Relationship(back_populates="traceability")


class TraceabilityRecordPublic(TraceabilityRecordBase):
    id: uuid.UUID
    batch_code: str


class TraceabilityRecordsPublic(SQLModel):
    data: list[TraceabilityRecordPublic]
    count: int


class BuyerBatchStage(SQLModel):
    status: Literal["HARVESTED", "STORED", "IN_TRANSIT", "DELIVERED"]
    recorded_at: datetime


class BuyerBatchHistory(SQLModel):
    batch_code: str
    crop: str
    county: str
    stages: list[BuyerBatchStage]


class FarmReportCreate(SQLModel):
    farm_id: uuid.UUID
    report_type: Literal[
        "FARM_SUMMARY", "INVENTORY", "EXPENSE", "HARVEST", "LOSS", "TRACEABILITY"
    ]
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class FarmReport(FarmReportCreate, table=True):
    report_type: Literal[
        "FARM_SUMMARY", "INVENTORY", "EXPENSE", "HARVEST", "LOSS", "TRACEABILITY"
    ] = Field(sa_type=String(30), index=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    farm_id: uuid.UUID = Field(foreign_key="farm.id", index=True)
    report_data: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    generated_at: datetime = Field(default_factory=get_datetime_utc)
    farm: Farm = Relationship(back_populates="reports")


class FarmReportPublic(FarmReportCreate):
    id: uuid.UUID
    report_data: dict[str, Any]
    generated_at: datetime


class FarmReportsPublic(SQLModel):
    data: list[FarmReportPublic]
    count: int


class ExpenseTotal(SQLModel):
    currency: Literal["LRD", "USD"]
    amount: Decimal


class HarvestTotal(SQLModel):
    crop_name: str
    unit: str
    quantity: Decimal


class LossTotal(SQLModel):
    loss_type: str
    unit: str
    crop_name: str | None
    quantity: Decimal


class FarmOverview(SQLModel):
    farm: FarmPublic
    inventory_item_count: int
    expenses: list[ExpenseTotal]
    harvests: list[HarvestTotal]
    losses: list[LossTotal]
    recent_inventory_movements: list[InventoryTransactionPublic]
    recent_harvests: list[HarvestPublic]
