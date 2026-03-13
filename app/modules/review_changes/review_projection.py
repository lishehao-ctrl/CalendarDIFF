from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeOrigin, SourceEventObservation
from app.modules.common.change_source_refs import source_refs_from_change
from app.modules.common.payload_schemas import (
    ChangeSourceRefPayload,
    ReviewChangeSummary,
    ReviewChangeSummarySide,
)
from app.modules.core_ingest.semantic_event_service import semantic_due_datetime_from_payload


@dataclass(frozen=True)
class ReviewProjectionContext:
    sources_by_id: dict[int, InputSource]
    observed_at_by_source_ref: dict[tuple[int, str], datetime]

    def proposal_sources(self, change: Change) -> list[ChangeSourceRefPayload]:
        proposal_sources = source_refs_from_change(change)
        if change.change_origin == ChangeOrigin.INGEST_PROPOSAL and not proposal_sources:
            raise RuntimeError(
                "review_projection_integrity_error: ingest proposal missing change_source_refs "
                f"change_id={change.id} entity_uid={change.entity_uid}"
            )
        return proposal_sources

    def primary_source(self, change: Change) -> dict | None:
        source_ref = self._primary_source_payload(change)
        return source_ref.to_primary_ref() if source_ref is not None else None

    def change_summary(self, change: Change) -> ReviewChangeSummary:
        before_payload = change.before_semantic_json if isinstance(change.before_semantic_json, dict) else None
        after_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else None
        primary_source_ref = self._primary_source_payload(change)
        old_source = (
            self._source_summary_from_ref(source_ref=primary_source_ref)
            if before_payload is not None and primary_source_ref is not None
            else ReviewChangeSummarySide()
        )
        new_source = (
            self._source_summary_from_ref(source_ref=primary_source_ref)
            if after_payload is not None and primary_source_ref is not None
            else ReviewChangeSummarySide()
        )
        return ReviewChangeSummary(
            old=ReviewChangeSummarySide(
                value_time=semantic_due_datetime_from_payload(before_payload) if before_payload is not None else None,
                source_label=old_source.source_label,
                source_kind=old_source.source_kind,
                source_observed_at=old_source.source_observed_at,
            ),
            new=ReviewChangeSummarySide(
                value_time=semantic_due_datetime_from_payload(after_payload) if after_payload is not None else None,
                source_label=new_source.source_label,
                source_kind=new_source.source_kind,
                source_observed_at=new_source.source_observed_at,
            ),
        )

    def _primary_source_payload(self, change: Change) -> ChangeSourceRefPayload | None:
        proposal_sources = self.proposal_sources(change)
        return proposal_sources[0] if proposal_sources else None

    def _source_summary_from_ref(
        self,
        *,
        source_ref: ChangeSourceRefPayload,
    ) -> ReviewChangeSummarySide:
        source = self.sources_by_id.get(source_ref.source_id)
        observed_at = None
        if isinstance(source_ref.external_event_id, str) and source_ref.external_event_id.strip():
            observed_at = self.observed_at_by_source_ref.get((source_ref.source_id, source_ref.external_event_id.strip()))
        return ReviewChangeSummarySide(
            source_label=_build_source_label(source=source, provider=source_ref.provider, source_kind=source_ref.source_kind),
            source_kind=_resolve_source_kind(source_kind=source_ref.source_kind, provider=source_ref.provider, source=source),
            source_observed_at=observed_at,
        )


def build_review_projection_context(db: Session, *, user_id: int, changes: list[Change]) -> ReviewProjectionContext:
    all_refs: list[ChangeSourceRefPayload] = []
    for change in changes:
        all_refs.extend(source_refs_from_change(change))

    source_ids = sorted({row.source_id for row in all_refs})
    sources_by_id: dict[int, InputSource] = {}
    if source_ids:
        source_rows = db.scalars(select(InputSource).where(InputSource.id.in_(source_ids))).all()
        sources_by_id = {int(row.id): row for row in source_rows}

    observed_at_by_source_ref: dict[tuple[int, str], datetime] = {}
    source_ref_pairs = sorted(
        {
            (row.source_id, row.external_event_id.strip())
            for row in all_refs
            if isinstance(row.external_event_id, str) and row.external_event_id.strip()
        }
    )
    if source_ref_pairs:
        rows = db.execute(
            select(
                SourceEventObservation.source_id,
                SourceEventObservation.external_event_id,
                func.max(SourceEventObservation.observed_at),
            )
            .where(
                SourceEventObservation.user_id == user_id,
                tuple_(
                    SourceEventObservation.source_id,
                    SourceEventObservation.external_event_id,
                ).in_(source_ref_pairs)
            )
            .group_by(SourceEventObservation.source_id, SourceEventObservation.external_event_id)
        ).all()
        observed_at_by_source_ref = {
            (int(source_id), external_event_id): observed_at
            for source_id, external_event_id, observed_at in rows
            if isinstance(source_id, int) and isinstance(external_event_id, str) and isinstance(observed_at, datetime)
        }

    return ReviewProjectionContext(
        sources_by_id=sources_by_id,
        observed_at_by_source_ref=observed_at_by_source_ref,
    )


def _build_source_label(*, source: InputSource | None, provider: str | None, source_kind: str | None) -> str | None:
    if source is not None and isinstance(source.display_name, str) and source.display_name.strip():
        return source.display_name.strip()
    if provider == "ics":
        return "Canvas ICS"
    if provider == "gmail":
        return "Gmail"
    if isinstance(source_kind, str) and source_kind.strip():
        return source_kind.strip().title()
    return None


def _resolve_source_kind(*, source_kind: str | None, provider: str | None, source: InputSource | None) -> str | None:
    if isinstance(source_kind, str) and source_kind.strip():
        return source_kind.strip().lower()
    if provider == "gmail":
        return "email"
    if provider == "ics":
        return "calendar"
    if source is not None:
        return source.source_kind.value
    return None


__all__ = [
    "ReviewProjectionContext",
    "build_review_projection_context",
]
