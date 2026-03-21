from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Literal

from app.db.models.review import ChangeType, EventEntity, EventEntityLifecycle, SourceEventObservation
from app.modules.common.change_evidence import freeze_observation_evidence, freeze_semantic_evidence
from app.modules.common.change_source_refs import normalize_source_refs, primary_source_from_refs, require_non_empty_source_refs
from app.modules.common.payload_schemas import ApprovedSemanticPayload, ChangeSourceRefPayload, FrozenChangeEvidence
from app.modules.common.semantic_codec import semantic_delta_seconds, semantic_payloads_equivalent
from app.modules.runtime.apply.observation_priority import choose_primary_observation


@dataclass(frozen=True)
class PendingProposalDecision:
    mode: Literal["reject", "upsert", "skip"]
    entity_uid: str
    change_type: ChangeType | None = None
    before_semantic: ApprovedSemanticPayload | None = None
    after_semantic: ApprovedSemanticPayload | None = None
    delta_seconds: int | None = None
    source_refs: list[ChangeSourceRefPayload] = field(default_factory=list)
    before_evidence: FrozenChangeEvidence | None = None
    after_evidence: FrozenChangeEvidence | None = None
    reject_note: str | None = None


def compute_pending_proposal_decision(
    *,
    entity_uid: str,
    observations: Sequence[SourceEventObservation],
    existing_entity: EventEntity | None,
    existing_entity_payload: ApprovedSemanticPayload | None = None,
    previous_observation_payload: dict | None = None,
    fallback_source_refs: Sequence[ChangeSourceRefPayload] | None = None,
    candidate_after_payload_fn,
    serialize_source_refs_fn,
) -> PendingProposalDecision:
    primary = choose_primary_observation(
        [
            {
                "source_kind": row.source_kind.value,
                "event_payload": row.event_payload,
                "observed_at": row.observed_at,
                "observation_id": int(row.id),
            }
            for row in observations
        ]
    )

    if primary is None and (existing_entity is None or existing_entity.lifecycle != EventEntityLifecycle.ACTIVE):
        return PendingProposalDecision(
            mode="reject",
            entity_uid=entity_uid,
            reject_note="proposal_resolved_no_active_observation",
        )

    if primary is None:
        if existing_entity is not None and existing_entity.manual_support:
            return PendingProposalDecision(
                mode="reject",
                entity_uid=entity_uid,
                reject_note="proposal_preserved_manual_support",
            )
        assert existing_entity_payload is not None
        source_refs = normalize_source_refs(list(fallback_source_refs or []))
        if not source_refs:
            return PendingProposalDecision(
                mode="reject",
                entity_uid=entity_uid,
                reject_note="removed_proposal_missing_source_refs",
            )
        primary_source_ref = primary_source_from_refs(source_refs)
        provider = primary_source_ref.get("provider") if isinstance(primary_source_ref, dict) else None
        return PendingProposalDecision(
            mode="upsert",
            entity_uid=entity_uid,
            change_type=ChangeType.REMOVED,
            before_semantic=existing_entity_payload,
            after_semantic=None,
            delta_seconds=None,
            source_refs=source_refs,
            before_evidence=freeze_observation_evidence(
                provider=provider,
                event_payload=previous_observation_payload,
                semantic_payload=existing_entity_payload.to_json_dict(),
            )
            or freeze_semantic_evidence(provider=provider, semantic_payload=existing_entity_payload.to_json_dict()),
            after_evidence=None,
        )

    primary_payload_raw = primary.get("event_payload")
    primary_payload = primary_payload_raw if isinstance(primary_payload_raw, dict) else {}
    candidate_after = candidate_after_payload_fn(entity_uid=entity_uid, payload=primary_payload)
    if candidate_after is None:
        return PendingProposalDecision(mode="skip", entity_uid=entity_uid)
    source_refs = require_non_empty_source_refs(
        source_refs=serialize_source_refs_fn(observations),
        context=f"proposal entity_uid={entity_uid}",
    )
    primary_source_ref = primary_source_from_refs(source_refs)
    after_evidence = freeze_observation_evidence(
        provider=primary_source_ref.get("provider") if isinstance(primary_source_ref, dict) else None,
        event_payload=primary_payload,
        semantic_payload=candidate_after.to_json_dict(),
    ) or freeze_semantic_evidence(
        provider=primary_source_ref.get("provider") if isinstance(primary_source_ref, dict) else None,
        semantic_payload=candidate_after.to_json_dict(),
    )

    if existing_entity is None or existing_entity.lifecycle != EventEntityLifecycle.ACTIVE:
        return PendingProposalDecision(
            mode="upsert",
            entity_uid=entity_uid,
            change_type=ChangeType.CREATED,
            before_semantic=None,
            after_semantic=candidate_after,
            delta_seconds=None,
            source_refs=source_refs,
            before_evidence=None,
            after_evidence=after_evidence,
        )

    before_semantic = existing_entity_payload
    if before_semantic is None:
        return PendingProposalDecision(mode="skip", entity_uid=entity_uid)
    if semantic_payloads_equivalent(before_semantic, candidate_after):
        return PendingProposalDecision(
            mode="reject",
            entity_uid=entity_uid,
            reject_note="proposal_already_matches_approved_entity_state",
        )

    return PendingProposalDecision(
        mode="upsert",
        entity_uid=entity_uid,
        change_type=ChangeType.DUE_CHANGED,
        before_semantic=before_semantic,
        after_semantic=candidate_after,
        delta_seconds=semantic_delta_seconds(before_payload=before_semantic, after_payload=candidate_after),
        source_refs=source_refs,
        before_evidence=freeze_observation_evidence(
            provider=None,
            event_payload=previous_observation_payload,
            semantic_payload=before_semantic.to_json_dict(),
        )
        or freeze_semantic_evidence(provider=None, semantic_payload=before_semantic.to_json_dict()),
        after_evidence=after_evidence,
    )


__all__ = [
    "PendingProposalDecision",
    "compute_pending_proposal_decision",
]
