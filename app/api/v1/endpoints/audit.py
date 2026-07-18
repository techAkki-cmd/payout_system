import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.audit import validate_user_wallet_integrity
from app.core.database import get_db
from app.models import User

router = APIRouter()
DBSession = Depends(get_db)


@router.get(
    "/wallet/{user_id}",
    summary="Validate wallet ledger integrity",
    description=(
        "Compares the user's wallet balance against the exact sum of append-only ledger rows."
    ),
)
def validate_wallet(user_id: uuid.UUID, db: Session = DBSession) -> dict[str, bool | str]:
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        validate_user_wallet_integrity(db, user_id)
        return {
            "is_valid": True,
            "message": "Wallet balance matches the append-only ledger.",
        }
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc
