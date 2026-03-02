from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MailLabel = Literal["KEEP", "DROP"]
MailEventClass = Literal[
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "action_required",
    "announcement",
    "grade",
    "null",
]
IcsDiffClass = Literal["DUE_CHANGED", "CREATED", "NO_CHANGE", "REMOVED_CANDIDATE"]


@dataclass(frozen=True)
class MailEvalSample:
    email_id: str
    from_addr: str | None
    subject: str | None
    date: str | None
    body_text: str | None
    gold_label: MailLabel
    gold_event_type: str | None
    ambiguous: bool


@dataclass(frozen=True)
class IcsEvalPair:
    pair_id: str
    before_content: bytes
    after_content: bytes
    expected_diff_class: IcsDiffClass
    expected_changed_uids: list[str] = field(default_factory=list)
    ambiguous: bool = False


@dataclass(frozen=True)
class EvalDataset:
    mail_samples: list[MailEvalSample]
    ics_pairs: list[IcsEvalPair]


@dataclass(frozen=True)
class MailEvalResult:
    email_id: str
    gold_label: MailLabel
    gold_event_type: str | None
    predicted_label: MailLabel | None
    predicted_event_type: str | None
    structured_success: bool
    ambiguous: bool
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class IcsEvalResult:
    pair_id: str
    expected_diff_class: IcsDiffClass
    predicted_diff_class: str | None
    expected_changed_uids: list[str]
    predicted_changed_uids: list[str]
    structured_success: bool
    ambiguous: bool
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ThresholdDecision:
    thresholds: dict[str, float]
    threshold_check: dict[str, bool]
    failed_checks: list[str]
    passed: bool


@dataclass(frozen=True)
class EvalSummary:
    mail_metrics: dict[str, Any]
    ics_metrics: dict[str, Any]
    decision: ThresholdDecision
