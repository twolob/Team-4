import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Item,
    ItemCreate,
    ItemPublic,
    ItemsPublic,
    ItemUpdate,
    Message,
    get_datetime_utc,
)
from app.services import records

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/", response_model=ItemsPublic)
def read_items(
    session: SessionDep,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    farm_id: uuid.UUID | None = None,
) -> Any:
    """
    Retrieve items.
    """

    statement = select(Item)
    if not current_user.is_superuser:
        statement = statement.where(col(Item.owner_id) == current_user.id)
    if farm_id:
        statement = statement.where(col(Item.farm_id) == farm_id)
    return records.page(
        session,
        statement.order_by(col(Item.created_at).desc(), col(Item.id)),
        skip,
        limit,
    )


@router.get("/{id}", response_model=ItemPublic)
def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get item by ID.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return item


@router.post("/", response_model=ItemPublic)
def create_item(
    *, session: SessionDep, current_user: CurrentUser, item_in: ItemCreate
) -> Any:
    """
    Create new item.
    """
    owner_id = current_user.id
    if item_in.farm_id:
        owner_id = records.owned_farm(session, current_user, item_in.farm_id).owner_id
    item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.patch("/{id}", response_model=ItemPublic)
@router.put("/{id}", response_model=ItemPublic)
def update_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: ItemUpdate,
) -> Any:
    """
    Update an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    update_dict = item_in.model_dump(exclude_unset=True)
    if "title" in update_dict and update_dict["title"] is None:
        raise HTTPException(422, "Title cannot be null")
    if "farm_id" in update_dict and update_dict["farm_id"] != item.farm_id:
        if item.transactions or item.farm_id is not None:
            raise HTTPException(409, "Existing farm inventory cannot be reassigned")
        if update_dict["farm_id"] is None:
            raise HTTPException(422, "Farm association is required")
        farm = records.owned_farm(session, current_user, update_dict["farm_id"])
        if farm.owner_id != item.owner_id:
            raise HTTPException(422, "Farm and item owners must match")
    if "unit" in update_dict and update_dict["unit"] != item.unit and item.transactions:
        raise HTTPException(409, "Unit cannot change after stock movements")
    item.sqlmodel_update(update_dict)
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{id}")
def delete_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete an item.
    """
    item = session.get(Item, id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (item.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    if item.transactions:
        raise HTTPException(409, "Item has stock history")
    session.delete(item)
    session.commit()
    return Message(message="Item deleted successfully")
