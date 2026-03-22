from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.review import Change, ChangeIntakePhase
from app.modules.runtime.apply.change_intake_policy import derive_review_bucket
from app.modules.runtime.apply.pending_change_store import resolve_pending_change_as_rejected, upsert_pending_change
from app.modules.runtime.apply.proposal_decision import PendingProposalDecision


def apply_pending_proposal_decision(
    *,
    db: Session,
    user_id: int,
    decision: PendingProposalDecision,
    applied_at: datetime,
    intake_phase: ChangeIntakePhase,
) -> Change | None:
    if decision.mode == "skip":
        return None
    if decision.mode == "reject":
        resolve_pending_change_as_rejected(
            db=db,
            user_id=user_id,
            entity_uid=decision.entity_uid,
            applied_at=applied_at,
            note=decision.reject_note or "proposal_rejected",
        )
        return None

    if decision.change_type is None:
        raise RuntimeError("upsert decision requires change_type")
    review_bucket = derive_review_bucket(
        intake_phase=intake_phase,
        change_type=decision.change_type,
    )
    return upsert_pending_change(
        db=db,
        user_id=user_id,
        entity_uid=decision.entity_uid,
        change_type=decision.change_type,
        intake_phase=intake_phase,
        review_bucket=review_bucket,
        before_semantic_json=decision.before_semantic.to_json_dict() if decision.before_semantic is not None else None,
        after_semantic_json=decision.after_semantic.to_json_dict() if decision.after_semantic is not None else None,
        delta_seconds=decision.delta_seconds,
        source_refs=[row.model_dump(mode="json") for row in decision.source_refs],
        detected_at=applied_at,
        before_evidence_json=decision.before_evidence.model_dump(mode="json") if decision.before_evidence is not None else None,
        after_evidence_json=decision.after_evidence.model_dump(mode="json") if decision.after_evidence is not None else None,
    )


__all__ = ["apply_pending_proposal_decision"]
