"""Authenticated farm record APIs. Foreign resources return 404."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    BuyerBatchHistory,
    BuyerBatchStage,
    Farm,
    FarmExpense,
    FarmExpenseCreate,
    FarmExpensePublic,
    FarmExpensesPublic,
    FarmExpenseUpdate,
    FarmOverview,
    FarmReport,
    FarmReportCreate,
    FarmReportPublic,
    FarmReportsPublic,
    Harvest,
    HarvestCreate,
    HarvestPublic,
    HarvestsPublic,
    HarvestUpdate,
    InventoryTransaction,
    InventoryTransactionCreate,
    InventoryTransactionPublic,
    InventoryTransactionsPublic,
    Item,
    LossRecord,
    LossRecordCreate,
    LossRecordPublic,
    LossRecordsPublic,
    LossRecordUpdate,
    Message,
    TraceabilityRecord,
    TraceabilityRecordCreate,
    TraceabilityRecordPublic,
    TraceabilityRecordsPublic,
)
from app.services import records

router = APIRouter(
    responses={
        401: {"description": "Authentication required"},
        404: {"description": "Record unavailable"},
        409: {"description": "Conflicting operation"},
        422: {"description": "Invalid input"},
    }
)
Skip = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.post(
    "/farm-expenses",
    response_model=FarmExpensePublic,
    status_code=201,
    tags=["FarmExpenses"],
)
def create_expense(
    body: FarmExpenseCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Create a record on an owned farm."""
    records.owned_farm(session, current_user, body.farm_id)
    return records.commit(session, FarmExpense.model_validate(body))


@router.get("/farm-expenses", response_model=FarmExpensesPublic, tags=["FarmExpenses"])
def list_expense(
    session: SessionDep,
    current_user: CurrentUser,
    farm_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
    category: str | None = None,
    currency: Literal["LRD", "USD"] | None = None,
) -> Any:
    """List accessible records with inclusive date and field filters."""
    query = records.visible_query(FarmExpense, current_user)
    if farm_id:
        query = query.where(col(FarmExpense.farm_id) == farm_id)
    if category is not None:
        query = query.where(FarmExpense.category == category)
    if currency is not None:
        query = query.where(col(FarmExpense.currency) == currency)
    query = query.where(
        *records.period_filter(
            col(FarmExpense.expense_date), start_date, end_date, False
        )
    ).order_by(col(FarmExpense.expense_date).desc(), col(FarmExpense.id))
    return records.page(session, query, skip, limit)


@router.get(
    "/farm-expenses/{record_id}",
    response_model=FarmExpensePublic,
    tags=["FarmExpenses"],
)
def read_expense(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Retrieve a record after resolving farm ownership."""
    return records.owned_record(session, current_user, FarmExpense, record_id)


@router.patch(
    "/farm-expenses/{record_id}",
    response_model=FarmExpensePublic,
    tags=["FarmExpenses"],
)
def update_expense(
    record_id: uuid.UUID,
    body: FarmExpenseUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Update record fields with full validation of the resulting record."""
    record = records.owned_record(session, current_user, FarmExpense, record_id)
    values = records.merged_update(record, body, FarmExpenseCreate)
    record.sqlmodel_update(values)
    return records.commit(session, record)


@router.delete(
    "/farm-expenses/{record_id}", response_model=Message, tags=["FarmExpenses"]
)
def delete_expense(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Delete a record, preserving dependent business history."""
    record = records.owned_record(session, current_user, FarmExpense, record_id)
    session.delete(record)
    session.commit()
    return Message(message="Record deleted successfully")


@router.post(
    "/harvests", response_model=HarvestPublic, status_code=201, tags=["Harvests"]
)
def create_harvest(
    body: HarvestCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Create a record on an owned farm."""
    records.owned_farm(session, current_user, body.farm_id)
    return records.commit(session, Harvest.model_validate(body))


@router.get("/harvests", response_model=HarvestsPublic, tags=["Harvests"])
def list_harvest(
    session: SessionDep,
    current_user: CurrentUser,
    farm_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
    crop_name: str | None = None,
) -> Any:
    """List accessible records with inclusive date and field filters."""
    query = records.visible_query(Harvest, current_user)
    if farm_id:
        query = query.where(col(Harvest.farm_id) == farm_id)
    if crop_name is not None:
        query = query.where(col(Harvest.crop_name) == crop_name)
    query = query.where(
        *records.period_filter(col(Harvest.harvest_date), start_date, end_date, False)
    ).order_by(col(Harvest.harvest_date).desc(), col(Harvest.id))
    return records.page(session, query, skip, limit)


@router.get("/harvests/{record_id}", response_model=HarvestPublic, tags=["Harvests"])
def read_harvest(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Retrieve a record after resolving farm ownership."""
    return records.owned_record(session, current_user, Harvest, record_id)


@router.patch("/harvests/{record_id}", response_model=HarvestPublic, tags=["Harvests"])
def update_harvest(
    record_id: uuid.UUID,
    body: HarvestUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Update record fields with full validation of the resulting record."""
    record = records.owned_record(session, current_user, Harvest, record_id)
    values = records.merged_update(record, body, HarvestCreate)
    if (values["unit"] != record.unit or values["crop_name"] != record.crop_name) and (
        record.traceability or record.losses
    ):
        raise HTTPException(409, "Crop and unit are fixed once dependent records exist")
    record.sqlmodel_update(values)
    return records.commit(session, record)


@router.delete("/harvests/{record_id}", response_model=Message, tags=["Harvests"])
def delete_harvest(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Delete a record, preserving dependent business history."""
    record = records.owned_record(session, current_user, Harvest, record_id)
    if record.traceability or record.losses:
        raise HTTPException(409, "Harvest has dependent records")
    session.delete(record)
    session.commit()
    return Message(message="Record deleted successfully")


@router.post(
    "/loss-records",
    response_model=LossRecordPublic,
    status_code=201,
    tags=["LossRecords"],
)
def create_loss(
    body: LossRecordCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Create a record on an owned farm."""
    records.owned_farm(session, current_user, body.farm_id)
    records.validate_loss(session, current_user, body)
    return records.commit(session, LossRecord.model_validate(body))


@router.get("/loss-records", response_model=LossRecordsPublic, tags=["LossRecords"])
def list_loss(
    session: SessionDep,
    current_user: CurrentUser,
    farm_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
    harvest_id: uuid.UUID | None = None,
    loss_type: str | None = None,
) -> Any:
    """List accessible records with inclusive date and field filters."""
    query = records.visible_query(LossRecord, current_user)
    if farm_id:
        query = query.where(col(LossRecord.farm_id) == farm_id)
    if harvest_id is not None:
        query = query.where(col(LossRecord.harvest_id) == harvest_id)
    if loss_type is not None:
        query = query.where(col(LossRecord.loss_type) == loss_type)
    query = query.where(
        *records.period_filter(col(LossRecord.recorded_at), start_date, end_date, True)
    ).order_by(col(LossRecord.recorded_at).desc(), col(LossRecord.id))
    return records.page(session, query, skip, limit)


@router.get(
    "/loss-records/{record_id}", response_model=LossRecordPublic, tags=["LossRecords"]
)
def read_loss(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Retrieve a record after resolving farm ownership."""
    return records.owned_record(session, current_user, LossRecord, record_id)


@router.patch(
    "/loss-records/{record_id}", response_model=LossRecordPublic, tags=["LossRecords"]
)
def update_loss(
    record_id: uuid.UUID,
    body: LossRecordUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Update record fields with full validation of the resulting record."""
    record = records.owned_record(session, current_user, LossRecord, record_id)
    values = records.merged_update(record, body, LossRecordCreate)
    records.validate_loss(
        session, current_user, LossRecordCreate.model_validate(values)
    )
    record.sqlmodel_update(values)
    return records.commit(session, record)


@router.delete(
    "/loss-records/{record_id}", response_model=Message, tags=["LossRecords"]
)
def delete_loss(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Delete a record, preserving dependent business history."""
    record = records.owned_record(session, current_user, LossRecord, record_id)
    session.delete(record)
    session.commit()
    return Message(message="Record deleted successfully")


@router.post(
    "/inventory-transactions",
    response_model=InventoryTransactionPublic,
    status_code=201,
    tags=["Inventory Transactions"],
)
def post_stock(
    body: InventoryTransactionCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Post stock atomically. ADJUSTMENT quantity is the target balance, including zero. Retry with the same idempotency_key."""
    return records.post_stock(session, current_user, body)


@router.get(
    "/inventory-transactions",
    response_model=InventoryTransactionsPublic,
    tags=["Inventory Transactions"],
)
def list_stock(
    session: SessionDep,
    current_user: CurrentUser,
    item_id: uuid.UUID | None = None,
    transaction_type: Literal["IN", "OUT", "ADJUSTMENT"] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
) -> Any:
    """List accessible movements by item, type and inclusive UTC dates."""
    query = records.visible_query(InventoryTransaction, current_user)
    if item_id:
        query = query.where(col(InventoryTransaction.item_id) == item_id)
    if transaction_type:
        query = query.where(
            col(InventoryTransaction.transaction_type) == transaction_type
        )
    query = query.where(
        *records.period_filter(
            col(InventoryTransaction.transaction_date), start_date, end_date, True
        )
    )
    return records.page(
        session,
        query.order_by(
            col(InventoryTransaction.transaction_date).desc(),
            col(InventoryTransaction.id),
        ),
        skip,
        limit,
    )


@router.get(
    "/inventory-transactions/{record_id}",
    response_model=InventoryTransactionPublic,
    tags=["Inventory Transactions"],
)
def read_stock(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    return records.owned_record(session, current_user, InventoryTransaction, record_id)


@router.post(
    "/traceability",
    response_model=TraceabilityRecordPublic,
    status_code=201,
    tags=["Traceability"],
)
def post_trace(
    body: TraceabilityRecordCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Append a batch event. Omit batch_code for the first event; reuse the returned code for subsequent events. event_key identifies retries."""
    return records.post_trace(session, current_user, body)


@router.get(
    "/traceability", response_model=TraceabilityRecordsPublic, tags=["Traceability"]
)
def list_trace(
    session: SessionDep,
    current_user: CurrentUser,
    harvest_id: uuid.UUID | None = None,
    farm_id: uuid.UUID | None = None,
    batch_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
) -> Any:
    query = records.visible_query(TraceabilityRecord, current_user)
    if harvest_id:
        query = query.where(col(TraceabilityRecord.harvest_id) == harvest_id)
    if farm_id:
        query = query.where(col(Harvest.farm_id) == farm_id)
    if batch_code:
        query = query.where(col(TraceabilityRecord.batch_code) == batch_code)
    query = query.where(
        *records.period_filter(
            col(TraceabilityRecord.recorded_at), start_date, end_date, True
        )
    )
    return records.page(
        session,
        query.order_by(col(TraceabilityRecord.recorded_at), col(TraceabilityRecord.id)),
        skip,
        limit,
    )


@router.get(
    "/traceability/batches/{batch_code}",
    response_model=TraceabilityRecordsPublic,
    tags=["Traceability"],
)
def batch_history(
    batch_code: str,
    session: SessionDep,
    current_user: CurrentUser,
    skip: Skip = 0,
    limit: Limit = 100,
) -> Any:
    query = records.visible_query(TraceabilityRecord, current_user).where(
        col(TraceabilityRecord.batch_code) == batch_code
    )
    result = records.page(
        session,
        query.order_by(col(TraceabilityRecord.recorded_at), col(TraceabilityRecord.id)),
        skip,
        limit,
    )
    if result["count"] == 0:
        raise HTTPException(404, "Batch not found")
    return result


@router.get(
    "/public/batches/{batch_code}",
    response_model=BuyerBatchHistory,
    tags=["Traceability"],
)
def public_batch_history(
    batch_code: str,
    session: SessionDep,
    skip: Skip = 0,
    limit: Limit = 100,
) -> BuyerBatchHistory:
    query = (
        select(
            TraceabilityRecord.status,
            TraceabilityRecord.recorded_at,
            Harvest.crop_name,
            Farm.county,
        )
        .join(Harvest, col(TraceabilityRecord.harvest_id) == col(Harvest.id))
        .join(Farm, col(Harvest.farm_id) == col(Farm.id))
        .where(col(TraceabilityRecord.batch_code) == batch_code)
        .order_by(col(TraceabilityRecord.recorded_at), col(TraceabilityRecord.id))
        .offset(skip)
        .limit(limit)
    )
    rows = session.exec(query).all()
    if not rows:
        raise HTTPException(404, "Batch history unavailable")
    _, _, crop, county = rows[0]
    return BuyerBatchHistory(
        batch_code=batch_code,
        crop=crop,
        county=county,
        stages=[
            BuyerBatchStage(status=status, recorded_at=recorded_at)
            for status, recorded_at, _, _ in rows
        ],
    )


@router.get(
    "/traceability/{record_id}",
    response_model=TraceabilityRecordPublic,
    tags=["Traceability"],
)
def read_trace(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    return records.owned_record(session, current_user, TraceabilityRecord, record_id)


@router.post(
    "/farm-reports/generate",
    response_model=FarmReportPublic,
    status_code=201,
    tags=["Farm Reports"],
)
def generate_report(
    body: FarmReportCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    """Generate an immutable snapshot from stored data. Repeating creates a new snapshot."""
    return records.generate_report(session, current_user, body)


@router.get("/farm-reports", response_model=FarmReportsPublic, tags=["Farm Reports"])
def list_reports(
    session: SessionDep,
    current_user: CurrentUser,
    farm_id: uuid.UUID | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
) -> Any:
    query = records.visible_query(FarmReport, current_user)
    if farm_id:
        query = query.where(col(FarmReport.farm_id) == farm_id)
    return records.page(
        session,
        query.order_by(col(FarmReport.generated_at).desc(), col(FarmReport.id)),
        skip,
        limit,
    )


@router.get(
    "/farm-reports/{record_id}", response_model=FarmReportPublic, tags=["Farm Reports"]
)
def read_report(
    record_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    return records.owned_record(session, current_user, FarmReport, record_id)


@router.get("/farms/{farm_id}/overview", response_model=FarmOverview, tags=["Farms"])
def farm_overview(
    farm_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    recent_limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Any:
    """Return lifetime totals with bounded recent activity and separate units/currencies."""
    farm = records.owned_farm(session, current_user, farm_id)
    totals = records.aggregates(session, farm_id)
    count = session.exec(
        select(func.count()).select_from(Item).where(col(Item.farm_id) == farm_id)
    ).one()
    movements = session.exec(
        select(InventoryTransaction)
        .join(Item)
        .where(col(Item.farm_id) == farm_id)
        .order_by(
            col(InventoryTransaction.created_at).desc(),
            col(InventoryTransaction.id),
        )
        .limit(recent_limit)
    ).all()
    harvests = session.exec(
        select(Harvest)
        .where(col(Harvest.farm_id) == farm_id)
        .order_by(
            col(Harvest.harvest_date).desc(),
            col(Harvest.id),
        )
        .limit(recent_limit)
    ).all()
    return {
        "farm": farm,
        "inventory_item_count": count,
        **totals,
        "recent_inventory_movements": movements,
        "recent_harvests": harvests,
    }
