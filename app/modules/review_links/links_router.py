from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.review_links.candidates_decision_service import LinkCandidateDecisionError
from app.modules.review_links.links_service import LinkNotFoundError, delete_link, list_links, relink_observation
from app.modules.review_links.router_common import raise_not_found, raise_unprocessable
from app.modules.review_links.schemas import LinkDeleteResponse, LinkItemResponse, LinkRelinkRequest, LinkRelinkResponse

router = APIRouter(prefix="/review/links")


@router.get("", response_model=list[LinkItemResponse])
def get_links(
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[LinkItemResponse]:
    rows = list_links(
        db=db,
        user_id=user.id,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [LinkItemResponse(**row) for row in rows]


@router.delete("/{link_id}", response_model=LinkDeleteResponse)
def delete_link_route(
    link_id: int,
    block: bool = Query(default=True),
    note: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkDeleteResponse:
    try:
        deleted_id, block_row = delete_link(
            db=db,
            user_id=user.id,
            link_id=link_id,
            create_block=block,
            note=note,
        )
    except LinkNotFoundError as exc:
        raise_not_found(exc)
    return LinkDeleteResponse(deleted=True, id=deleted_id, block_id=block_row.id if block_row is not None else None)


@router.post("/relink", response_model=LinkRelinkResponse)
def post_relink_observation(
    payload: LinkRelinkRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkRelinkResponse:
    try:
        row, cleared = relink_observation(
            db=db,
            user_id=user.id,
            source_id=payload.source_id,
            external_event_id=payload.external_event_id.strip(),
            entity_uid=payload.entity_uid.strip(),
            clear_block=payload.clear_block,
            note=payload.note,
        )
    except LinkCandidateDecisionError as exc:
        raise_unprocessable(exc)

    return LinkRelinkResponse(
        link_id=row.id,
        entity_uid=row.entity_uid,
        source_id=row.source_id,
        external_event_id=row.external_event_id,
        cleared_blocks=cleared,
    )


__all__ = ["router"]
