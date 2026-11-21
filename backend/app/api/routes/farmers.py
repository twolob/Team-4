import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.security import get_password_hash
from app.models import (
    Farm,
    FarmCreate,
    FarmerProfileUpdate,
    FarmerRegister,
    FarmerRegistration,
    FarmPublic,
    FarmUpdate,
    Message,
    User,
    UserPublic,
)
from app.services import records

router = APIRouter(tags=["farmers"])


@router.post("/farmers/signup", response_model=FarmerRegistration, status_code=201)
def register_farmer(body: FarmerRegister, session: SessionDep) -> Any:
    user = User(
        full_name=body.full_name,
        phone_number=body.phone_number,
        email=body.email,
        hashed_password=get_password_hash(body.password),
    )
    farm = Farm.model_validate(body.farm, update={"owner_id": user.id})
    session.add(user)
    session.add(farm)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Phone number or email already registered"
        )
    session.refresh(user)
    session.refresh(farm)
    return FarmerRegistration(
        user=UserPublic.model_validate(user), farm=FarmPublic.model_validate(farm)
    )


@router.patch("/farmers/me", response_model=UserPublic)
def update_profile(
    body: FarmerProfileUpdate, session: SessionDep, current_user: CurrentUser
) -> Any:
    current_user.full_name = body.full_name
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.post("/farms/", response_model=FarmPublic, status_code=201)
def create_farm(
    body: FarmCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    farm = Farm.model_validate(body, update={"owner_id": current_user.id})
    session.add(farm)
    session.commit()
    session.refresh(farm)
    return farm


@router.get("/farms/", response_model=list[FarmPublic])
def list_farms(
    session: SessionDep,
    current_user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Any:
    query = select(Farm)
    if not current_user.is_superuser:
        query = query.where(col(Farm.owner_id) == current_user.id)
    return session.exec(
        query.order_by(col(Farm.created_at).desc(), col(Farm.id))
        .offset(skip)
        .limit(limit)
    ).all()


def owned_farm(farm_id: uuid.UUID, session: Session, user: User) -> Farm:
    return records.owned_farm(session, user, farm_id)


@router.get("/farms/{farm_id}", response_model=FarmPublic)
def read_farm(
    farm_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    return owned_farm(farm_id, session, current_user)


@router.put("/farms/{farm_id}", response_model=FarmPublic)
def update_farm(
    farm_id: uuid.UUID, body: FarmCreate, session: SessionDep, current_user: CurrentUser
) -> Any:
    farm = owned_farm(farm_id, session, current_user)
    farm.sqlmodel_update(body.model_dump())
    session.add(farm)
    session.commit()
    session.refresh(farm)
    return farm


@router.patch("/farms/{farm_id}", response_model=FarmPublic, tags=["Farms"])
def patch_farm(
    farm_id: uuid.UUID, body: FarmUpdate, session: SessionDep, current_user: CurrentUser
) -> Any:
    farm = records.owned_farm(session, current_user, farm_id)
    farm.sqlmodel_update(records.merged_update(farm, body, FarmCreate))
    return records.commit(session, farm)


@router.delete("/farms/{farm_id}", response_model=Message, tags=["Farms"])
def delete_farm(
    farm_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    farm = records.owned_farm(session, current_user, farm_id)
    if farm.items or farm.expenses or farm.harvests or farm.losses or farm.reports:
        raise HTTPException(409, "Farm has business records")
    session.delete(farm)
    session.commit()
    return Message(message="Farm deleted successfully")
