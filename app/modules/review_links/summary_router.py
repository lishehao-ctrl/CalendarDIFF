from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.review_links.schemas import ReviewItemsSummaryResponse
from app.modules.review_links.summary_service import get_review_items_summary

router = APIRouter()


@router.get("/review/summary", response_model=ReviewItemsSummaryResponse)
def get_review_items_summary_route(
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewItemsSummaryResponse:
    payload = get_review_items_summary(db=db, user_id=user.id)
    return ReviewItemsSummaryResponse(**payload)


__all__ = ["router"]
