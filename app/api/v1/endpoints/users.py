import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.schemas import UserCreateRequest, UserResponse

router = APIRouter()
DBSession = Depends(get_db)


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a demo creator",
    description="Creates a creator wallet with a zero balance for dashboard demonstrations.",
)
def create_user(payload: UserCreateRequest, db: Session = DBSession) -> User:
    try:
        user = User(username=payload.username)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Fetch a creator wallet",
    description="Returns the wallet state used by the dashboard balance and lock indicator.",
)
def get_user(user_id: uuid.UUID, db: Session = DBSession) -> User:
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        return user
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc
