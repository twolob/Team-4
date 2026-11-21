"""Farm authorization, stock posting, traceability, and reporting services."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.models import (
    Farm,
    FarmExpense,
    FarmReport,
    FarmReportCreate,
    Harvest,
    InventoryTransaction,
    InventoryTransactionCreate,
    Item,
    LossRecord,
    TraceabilityRecord,
    TraceabilityRecordCreate,
    User,
    get_datetime_utc,
)


def owned_farm(session: Session, user: User, farm_id: uuid.UUID) -> Farm:
    farm = session.get(Farm, farm_id)
    if farm is None or (not user.is_superuser and farm.owner_id != user.id):
        raise HTTPException(404, "Farm not found")
    return farm


def owned_record(session: Session, user: User, model: Any, record_id: uuid.UUID) -> Any:
    record = session.get(model, record_id)
    if record is None:
        raise HTTPException(404, "Record not found")
    if isinstance(record, Item):
        if not user.is_superuser and record.owner_id != user.id:
            raise HTTPException(404, "Record not found")
    elif isinstance(record, InventoryTransaction):
        owned_record(session, user, Item, record.item_id)
    elif isinstance(record, TraceabilityRecord):
        owned_record(session, user, Harvest, record.harvest_id)
    else:
        owned_farm(session, user, record.farm_id)
    return record


def visible_query(model: Any, user: User) -> Any:
    query = select(model)
    if model is InventoryTransaction:
        query = query.join(Item, col(InventoryTransaction.item_id) == col(Item.id))
        if not user.is_superuser:
            query = query.where(col(Item.owner_id) == user.id)
    elif model is TraceabilityRecord:
        query = query.join(Harvest).join(Farm)
        if not user.is_superuser:
            query = query.where(col(Farm.owner_id) == user.id)
    else:
        query = query.join(Farm)
        if not user.is_superuser:
            query = query.where(col(Farm.owner_id) == user.id)
    return query


def page(session: Session, query: Any, skip: int, limit: int) -> dict[str, Any]:
    count = session.exec(
        select(func.count()).select_from(query.order_by(None).subquery())
    ).one()
    return {"data": session.exec(query.offset(skip).limit(limit)).all(), "count": count}


def commit(session: Session, record: Any) -> Any:
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "Record conflicts with existing data or dependent history"
        )
    session.refresh(record)
    return record


def validate_loss(session: Session, user: User, body: Any) -> None:
    owned_farm(session, user, body.farm_id)
    if body.harvest_id:
        harvest = owned_record(session, user, Harvest, body.harvest_id)
        if harvest.farm_id != body.farm_id:
            raise HTTPException(422, "Harvest must belong to the same farm")
        if harvest.unit != body.unit:
            raise HTTPException(422, "Loss unit must match the linked harvest unit")


def merged_update(record: Any, body: Any, create_schema: Any) -> dict[str, Any]:
    values = record.model_dump()
    values.update(body.model_dump(exclude_unset=True))
    try:
        return create_schema.model_validate(values).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, str(exc))


def post_stock(
    session: Session, user: User, body: InventoryTransactionCreate
) -> InventoryTransaction:
    item = owned_record(session, user, Item, body.item_id)
    if item.farm_id is None:
        raise HTTPException(422, "Associate the item with a farm before posting stock")
    existing = session.exec(
        select(InventoryTransaction).where(
            col(InventoryTransaction.item_id) == item.id,
            col(InventoryTransaction.idempotency_key) == body.idempotency_key,
        )
    ).first()
    if existing:
        if (existing.transaction_type, existing.quantity, existing.notes) != (
            body.transaction_type,
            body.quantity,
            body.notes,
        ):
            raise HTTPException(
                409, "Idempotency key already used for a different movement"
            )
        return existing
    query = update(Item).where(col(Item.id) == item.id)
    new_quantity = col(Item.quantity) + body.quantity
    if body.transaction_type == "OUT":
        new_quantity = col(Item.quantity) - body.quantity
    if session.get_bind().dialect.name == "sqlite":
        new_quantity = func.round(new_quantity, 4)
    if body.transaction_type == "OUT":
        query = query.where(col(Item.quantity) >= body.quantity).values(
            quantity=new_quantity
        )
    elif body.transaction_type == "IN":
        query = query.values(quantity=new_quantity)
    else:
        query = query.values(quantity=body.quantity)
    result = session.exec(
        query.values(updated_at=get_datetime_utc()).execution_options(
            synchronize_session=False
        )
    )
    if cast(CursorResult, result).rowcount != 1:
        session.rollback()
        existing = session.exec(
            select(InventoryTransaction).where(
                col(InventoryTransaction.item_id) == body.item_id,
                col(InventoryTransaction.idempotency_key) == body.idempotency_key,
            )
        ).first()
        if existing and (
            existing.transaction_type,
            existing.quantity,
            existing.notes,
        ) == (body.transaction_type, body.quantity, body.notes):
            return existing
        raise HTTPException(409, "Insufficient stock or conflicting retry")
    session.refresh(item)
    movement = InventoryTransaction.model_validate(
        body,
        update={
            "balance_after": item.quantity,
            "transaction_date": body.transaction_date.astimezone(UTC),
        },
    )
    session.add(movement)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(InventoryTransaction).where(
                col(InventoryTransaction.item_id) == body.item_id,
                col(InventoryTransaction.idempotency_key) == body.idempotency_key,
            )
        ).first()
        if existing and (
            existing.transaction_type,
            existing.quantity,
            existing.notes,
        ) == (body.transaction_type, body.quantity, body.notes):
            return existing
        raise HTTPException(409, "Conflicting stock request")
    session.refresh(movement)
    return movement


def post_trace(
    session: Session, user: User, body: TraceabilityRecordCreate
) -> TraceabilityRecord:
    harvest = owned_record(session, user, Harvest, body.harvest_id)
    # Locking the harvest serializes creation of batch events on PostgreSQL.
    session.exec(
        select(Harvest).where(col(Harvest.id) == harvest.id).with_for_update()
    ).one()
    existing = session.exec(
        select(TraceabilityRecord).where(
            col(TraceabilityRecord.harvest_id) == harvest.id,
            col(TraceabilityRecord.event_key) == body.event_key,
        )
    ).first()
    if existing:
        if (existing.status, existing.origin, existing.destination) != (
            body.status,
            body.origin,
            body.destination,
        ):
            raise HTTPException(409, "Event key already used")
        return existing
    if body.recorded_at.tzinfo is None:
        raise HTTPException(422, "recorded_at must include a timezone")
    values = body.model_dump()
    values["recorded_at"] = body.recorded_at.astimezone(UTC)
    if body.batch_code:
        # Generated codes encode the original harvest, preventing cross-harvest races.
        prefix = f"AG-{harvest.id.hex}-"
        if not body.batch_code.startswith(prefix):
            raise HTTPException(422, "Use the batch code returned by the first event")
        origin = session.exec(
            select(TraceabilityRecord)
            .where(
                col(TraceabilityRecord.batch_code) == body.batch_code,
            )
            .order_by(col(TraceabilityRecord.recorded_at), col(TraceabilityRecord.id))
        ).first()
        if origin is None or origin.harvest_id != harvest.id:
            raise HTTPException(422, "Unknown batch for this harvest")
        if body.origin != origin.origin or values["recorded_at"].replace(
            tzinfo=None
        ) < origin.recorded_at.replace(tzinfo=None):
            raise HTTPException(
                422, "Batch origin and chronology must match the first event"
            )
    else:
        # UUID event keys are unique per harvest, and the harvest UUID namespaces codes.
        values["batch_code"] = f"AG-{harvest.id.hex}-{body.event_key.hex}"
    return commit(session, TraceabilityRecord.model_validate(values))


def period_filter(
    column: Any, start: date | None, end: date | None, timestamp: bool = False
) -> list[Any]:
    if start and end and end < start:
        raise HTTPException(422, "end_date must be on or after start_date")
    conditions = []
    if start:
        conditions.append(
            column >= (datetime.combine(start, time.min, UTC) if timestamp else start)
        )
    if end:
        conditions.append(
            column < datetime.combine(end + timedelta(days=1), time.min, UTC)
            if timestamp
            else column <= end
        )
    return conditions


def aggregates(
    session: Session,
    farm_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    expenses = session.exec(
        select(col(FarmExpense.currency), func.sum(col(FarmExpense.amount)))
        .where(
            col(FarmExpense.farm_id) == farm_id,
            *period_filter(col(FarmExpense.expense_date), start, end),
        )
        .group_by(col(FarmExpense.currency))
    ).all()
    harvests = session.exec(
        select(
            col(Harvest.crop_name), col(Harvest.unit), func.sum(col(Harvest.quantity))
        )
        .where(
            col(Harvest.farm_id) == farm_id,
            *period_filter(col(Harvest.harvest_date), start, end),
        )
        .group_by(col(Harvest.crop_name), col(Harvest.unit))
    ).all()
    losses = session.exec(
        select(
            col(LossRecord.loss_type),
            col(LossRecord.unit),
            col(Harvest.crop_name),
            func.sum(col(LossRecord.quantity)),
        )
        .outerjoin(
            Harvest,
            col(LossRecord.harvest_id) == col(Harvest.id),
        )
        .where(
            col(LossRecord.farm_id) == farm_id,
            *period_filter(col(LossRecord.recorded_at), start, end, True),
        )
        .group_by(
            col(LossRecord.loss_type),
            col(LossRecord.unit),
            col(Harvest.crop_name),
        )
    ).all()
    return {
        "expenses": [
            {"currency": currency, "amount": str(amount)}
            for currency, amount in expenses
        ],
        "harvests": [
            {"crop_name": crop, "unit": unit, "quantity": str(quantity)}
            for crop, unit, quantity in harvests
        ],
        "losses": [
            {
                "loss_type": kind,
                "unit": unit,
                "crop_name": crop,
                "quantity": str(quantity),
            }
            for kind, unit, crop, quantity in losses
        ],
    }


def generate_report(session: Session, user: User, body: FarmReportCreate) -> FarmReport:
    owned_farm(session, user, body.farm_id)
    totals = aggregates(session, body.farm_id, body.period_start, body.period_end)
    data = {
        "period_start": str(body.period_start),
        "period_end": str(body.period_end),
        "methodology": "Inclusive UTC dates; expenses grouped by currency; production by crop and unit; losses by type, crop and unit. Losses do not alter stock. Inventory is current balance at generation; movements are grouped by item, type and unit for the period.",
    }
    sections = {"EXPENSE": "expenses", "HARVEST": "harvests", "LOSS": "losses"}
    if body.report_type == "FARM_SUMMARY":
        data.update(totals)
    elif body.report_type in sections:
        key = sections[body.report_type]
        data[key] = totals[key]
    if body.report_type in {"INVENTORY", "FARM_SUMMARY"}:
        balances = session.exec(
            select(
                col(Item.unit), func.count(col(Item.id)), func.sum(col(Item.quantity))
            )
            .where(
                col(Item.farm_id) == body.farm_id,
            )
            .group_by(col(Item.unit))
        ).all()
        data["inventory"] = [
            {"unit": unit, "item_count": count, "quantity": str(quantity)}
            for unit, count, quantity in balances
        ]
        movements = session.exec(
            select(
                col(InventoryTransaction.item_id),
                col(Item.unit),
                col(InventoryTransaction.transaction_type),
                func.sum(col(InventoryTransaction.quantity)),
            )
            .join(Item)
            .where(
                col(Item.farm_id) == body.farm_id,
                *period_filter(
                    col(InventoryTransaction.transaction_date),
                    body.period_start,
                    body.period_end,
                    True,
                ),
            )
            .group_by(
                col(InventoryTransaction.item_id),
                col(Item.unit),
                col(InventoryTransaction.transaction_type),
            )
        ).all()
        data["movements"] = [
            {
                "item_id": str(item_id),
                "unit": unit,
                "type": kind,
                "quantity": str(quantity),
                "meaning": "sum of target balances"
                if kind == "ADJUSTMENT"
                else "total moved",
            }
            for item_id, unit, kind, quantity in movements
        ]
    if body.report_type in {"TRACEABILITY", "FARM_SUMMARY"}:
        events = session.exec(
            select(
                col(TraceabilityRecord.status), func.count(col(TraceabilityRecord.id))
            )
            .join(Harvest)
            .where(
                col(Harvest.farm_id) == body.farm_id,
                *period_filter(
                    col(TraceabilityRecord.recorded_at),
                    body.period_start,
                    body.period_end,
                    True,
                ),
            )
            .group_by(col(TraceabilityRecord.status))
        ).all()
        data["traceability"] = [
            {"status": status, "event_count": count} for status, count in events
        ]
    return commit(
        session, FarmReport.model_validate(body, update={"report_data": data})
    )
