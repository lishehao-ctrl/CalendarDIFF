#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.models.agents import AgentProposal
from app.db.models.shared import User
from app.db.session import get_session_factory
from app.modules.agents.schemas import serialize_agent_proposal
from app.modules.common.language import DEFAULT_LANGUAGE_CODE
from app.modules.llm_gateway import LlmInvokeRequest, invoke_llm_json
from app.modules.llm_gateway.costing import estimate_llm_usage_cost, merge_llm_cost_summary

OUTPUT_ROOT = REPO_ROOT / "output"
RESULTS_FILE = "proposal-quality-results.jsonl"
SUMMARY_FILE = "proposal-quality-summary.json"
SUMMARY_MD_FILE = "proposal-quality-summary.md"
JUDGE_MODES = {"deterministic", "llm", "off"}

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator for CalendarDIFF bounded-review agent proposal copy. "
    "Evaluate only narrative quality, explanation quality, and language fit. "
    "Do not override provided deterministic flags. "
    "Do not invent new facts. "
    "Return JSON only."
)


@dataclass(frozen=True)
class ProposalQualityRow:
    proposal_id: int
    proposal_type: str
    target_kind: str
    target_id: str
    language_code: str
    summary: str
    reason: str
    risk_level: str
    suggested_action: str
    execution_mode: str
    status: str
    grounding_correct: bool
    action_correct: bool
    execution_mode_correct: bool
    risk_label_correct: bool
    language_match: bool
    forbidden_action_absent: bool
    summary_quality_score: float
    reason_quality_score: float
    summary_naturalness_score: float | None = None
    reason_naturalness_score: float | None = None
    boundary_explanation_score: float | None = None
    judge_language_match: bool | None = None
    judge_overall_score: float | None = None
    judge_available: bool = False
    judge_notes: list[str] | None = None
    judge_usage: dict[str, int] | None = None
    judge_cost: dict[str, Any] | None = None
    overall_quality_score: float = 0.0
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate persisted agent proposal quality with deterministic checks.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--language-code", default=DEFAULT_LANGUAGE_CODE)
    parser.add_argument("--judge-mode", default="deterministic", choices=sorted(JUDGE_MODES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"agent-proposal-quality-eval-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = load_proposals(
        email=str(args.email),
        limit=max(int(args.limit), 1),
        language_code=str(args.language_code),
        judge_mode=str(args.judge_mode),
    )
    for row in rows:
        append_jsonl(run_dir / RESULTS_FILE, row.to_dict())
    summary = compute_summary(rows, judge_mode=str(args.judge_mode))
    write_json(run_dir / SUMMARY_FILE, summary)
    (run_dir / SUMMARY_MD_FILE).write_text(render_summary_markdown(summary=summary, rows=rows), encoding="utf-8")
    print(run_dir)


def load_proposals(*, email: str, limit: int, language_code: str, judge_mode: str) -> list[ProposalQualityRow]:
    session_factory = get_session_factory()
    with session_factory() as db:
        user = db.scalar(select(User).where(User.email == email).limit(1))
        if user is None:
            raise RuntimeError(f"user not found for proposal quality eval: {email}")
        proposals = list(
            db.scalars(
                select(AgentProposal)
                .where(AgentProposal.user_id == user.id)
                .order_by(AgentProposal.created_at.desc(), AgentProposal.id.desc())
                .limit(limit)
            ).all()
        )
        return [_score_row(db=db, row=row, language_code=language_code, judge_mode=judge_mode) for row in proposals]


def _score_row(db, row: AgentProposal, *, language_code: str, judge_mode: str) -> ProposalQualityRow:
    payload = serialize_agent_proposal(row, language_code=language_code, language_resolution_source="explicit")
    summary = str(payload.get("summary") or "")
    reason = str(payload.get("reason") or "")
    target_snapshot = payload.get("target_snapshot") if isinstance(payload.get("target_snapshot"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    suggested_payload = payload.get("suggested_payload") if isinstance(payload.get("suggested_payload"), dict) else {}
    notes: list[str] = []

    grounding_correct = _target_grounding_present(
        payload=payload,
        context=context,
        target_snapshot=target_snapshot,
        suggested_payload=suggested_payload,
    )
    if not grounding_correct:
        notes.append("missing_grounding")

    action_correct = _action_matches_payload(
        suggested_action=str(payload.get("suggested_action") or ""),
        suggested_payload=suggested_payload,
    )
    if not action_correct:
        notes.append("action_payload_mismatch")

    execution_mode_correct = _execution_mode_matches_payload(
        execution_mode=str(payload.get("execution_mode") or ""),
        suggested_payload=suggested_payload,
    )
    if not execution_mode_correct:
        notes.append("execution_mode_mismatch")

    risk_label_correct = _risk_label_matches_context(
        risk_level=str(payload.get("risk_level") or ""),
        context=context,
    )
    if not risk_label_correct:
        notes.append("risk_level_mismatch")

    language_match = _language_matches_texts(language_code=language_code, texts=(summary, reason))
    if not language_match:
        notes.append("language_mismatch")

    forbidden_action_absent = _forbidden_action_absent(texts=(summary, reason))
    if not forbidden_action_absent:
        notes.append("forbidden_action_language")

    summary_quality_score = _quality_score(text=summary, long_limit=90)
    reason_quality_score = _quality_score(text=reason, long_limit=260)
    judge_payload = _judge_narrative(
        db=db,
        judge_mode=judge_mode,
        payload=payload,
        summary=summary,
        reason=reason,
        deterministic_flags={
            "grounding_correct": grounding_correct,
            "action_correct": action_correct,
            "execution_mode_correct": execution_mode_correct,
            "risk_label_correct": risk_label_correct,
            "language_match": language_match,
            "forbidden_action_absent": forbidden_action_absent,
        },
    )
    bool_scores = [
        1.0 if grounding_correct else 0.0,
        1.0 if action_correct else 0.0,
        1.0 if execution_mode_correct else 0.0,
        1.0 if risk_label_correct else 0.0,
        1.0 if language_match else 0.0,
        1.0 if forbidden_action_absent else 0.0,
    ]
    deterministic_structural_score = sum(bool_scores) / len(bool_scores)
    deterministic_narrative_score = (summary_quality_score + reason_quality_score) / 2
    judge_overall_score = judge_payload.get("judge_overall_score") if isinstance(judge_payload.get("judge_overall_score"), float) else None
    narrative_score = judge_overall_score if judge_overall_score is not None else deterministic_narrative_score
    overall_quality_score = round((deterministic_structural_score * 0.7) + (narrative_score * 0.3), 4)

    return ProposalQualityRow(
        proposal_id=int(payload.get("proposal_id") or getattr(row, "id", 0) or 0),
        proposal_type=str(payload.get("proposal_type") or ""),
        target_kind=str(payload.get("target_kind") or ""),
        target_id=str(payload.get("target_id") or ""),
        language_code=str(payload.get("language_code") or language_code),
        summary=summary,
        reason=reason,
        risk_level=str(payload.get("risk_level") or ""),
        suggested_action=str(payload.get("suggested_action") or ""),
        execution_mode=str(payload.get("execution_mode") or ""),
        status=str(payload.get("status") or ""),
        grounding_correct=grounding_correct,
        action_correct=action_correct,
        execution_mode_correct=execution_mode_correct,
        risk_label_correct=risk_label_correct,
        language_match=language_match,
        forbidden_action_absent=forbidden_action_absent,
        summary_quality_score=summary_quality_score,
        reason_quality_score=reason_quality_score,
        summary_naturalness_score=judge_payload.get("summary_naturalness_score"),
        reason_naturalness_score=judge_payload.get("reason_naturalness_score"),
        boundary_explanation_score=judge_payload.get("boundary_explanation_score"),
        judge_language_match=judge_payload.get("judge_language_match"),
        judge_overall_score=judge_overall_score,
        judge_available=bool(judge_payload.get("judge_available")),
        judge_notes=list(judge_payload.get("judge_notes") or []),
        judge_usage=judge_payload.get("judge_usage"),
        judge_cost=judge_payload.get("judge_cost"),
        overall_quality_score=overall_quality_score,
        notes=notes,
    )


def compute_summary(rows: list[ProposalQualityRow], judge_mode: str = "deterministic") -> dict[str, Any]:
    count = len(rows)
    judge_available_count = sum(1 for row in rows if row.judge_available)
    token_usage = {"overall": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
    cost_usd = {"overall": {"estimated_cost_usd": 0.0, "input_cost_usd": 0.0, "cached_input_cost_usd": 0.0, "output_cost_usd": 0.0, "pricing_available": True, "unpriced_call_count": 0}}
    for row in rows:
        usage = getattr(row, "judge_usage", None)
        if isinstance(usage, dict):
            for key in token_usage["overall"]:
                token_usage["overall"][key] += max(int(usage.get(key) or 0), 0)
        estimate = getattr(row, "judge_cost", None)
        if isinstance(estimate, dict):
            cost_usd["overall"].update(merge_llm_cost_summary(cost_usd["overall"], estimate=estimate))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "proposal_count": count,
        "grounding_correct_rate": _ratio(sum(1 for row in rows if row.grounding_correct), count),
        "action_correct_rate": _ratio(sum(1 for row in rows if row.action_correct), count),
        "execution_mode_correct_rate": _ratio(sum(1 for row in rows if row.execution_mode_correct), count),
        "risk_label_correct_rate": _ratio(sum(1 for row in rows if row.risk_label_correct), count),
        "language_match_rate": _ratio(sum(1 for row in rows if row.language_match), count),
        "forbidden_action_absent_rate": _ratio(sum(1 for row in rows if row.forbidden_action_absent), count),
        "summary_quality_score_avg": _avg(row.summary_quality_score for row in rows),
        "reason_quality_score_avg": _avg(row.reason_quality_score for row in rows),
        "overall_quality_score_avg": _avg(row.overall_quality_score for row in rows),
        "judge_enabled": judge_mode == "llm",
        "judge_available_rate": _ratio(judge_available_count, count),
        "judge_fallback_count": count - judge_available_count,
        "judge_overall_score_avg": _avg(row.judge_overall_score for row in rows if row.judge_overall_score is not None),
        "token_usage": token_usage,
        "cost_usd": cost_usd,
        "low_score_count": sum(1 for row in rows if row.overall_quality_score < 0.8),
    }


def render_summary_markdown(*, summary: dict[str, Any], rows: list[ProposalQualityRow]) -> str:
    lines = [
        "# Agent Proposal Quality Eval",
        "",
        f"- Proposal count: `{summary['proposal_count']}`",
        f"- Grounding correct rate: `{_fmt_ratio(summary['grounding_correct_rate'])}`",
        f"- Action correct rate: `{_fmt_ratio(summary['action_correct_rate'])}`",
        f"- Execution mode correct rate: `{_fmt_ratio(summary['execution_mode_correct_rate'])}`",
        f"- Risk label correct rate: `{_fmt_ratio(summary['risk_label_correct_rate'])}`",
        f"- Language match rate: `{_fmt_ratio(summary['language_match_rate'])}`",
        f"- Forbidden action absent rate: `{_fmt_ratio(summary['forbidden_action_absent_rate'])}`",
        f"- Overall quality avg: `{summary['overall_quality_score_avg']}`",
        f"- Judge available rate: `{_fmt_ratio(summary['judge_available_rate'])}`",
        f"- Judge overall avg: `{summary['judge_overall_score_avg']}`",
        f"- Judge total tokens: `{summary['token_usage']['overall']['total_tokens']}`",
        f"- Judge estimated cost usd: `{summary['cost_usd']['overall']['estimated_cost_usd']}`",
        "",
    ]
    low_rows = [row for row in rows if row.overall_quality_score < 0.8][:10]
    if low_rows:
        lines.extend(["## Lowest Rows", ""])
        for row in low_rows:
            lines.append(f"- proposal `{row.proposal_id}` `{row.proposal_type}` score={row.overall_quality_score} notes={','.join(row.notes) or 'none'}")
        lines.append("")
    return "\n".join(lines)


def _target_grounding_present(*, payload: dict[str, Any], context: dict[str, Any], target_snapshot: dict[str, Any], suggested_payload: dict[str, Any]) -> bool:
    target_kind = str(payload.get("target_kind") or "")
    target_id = str(payload.get("target_id") or "")
    if not target_kind or not target_id:
        return False
    candidate_keys = {
        "change": ("change_id",),
        "source": ("source_id",),
        "family": ("family_id", "target_family_id"),
    }.get(target_kind, ())
    observed = []
    for mapping in (context, target_snapshot, suggested_payload):
        if not isinstance(mapping, dict):
            continue
        for key in candidate_keys:
            value = mapping.get(key)
            if value is not None:
                observed.append(str(value))
    if not observed:
        joined = json.dumps([context, target_snapshot, suggested_payload], ensure_ascii=False, sort_keys=True)
        return target_id in joined
    return all(value == target_id for value in observed)


def _action_matches_payload(*, suggested_action: str, suggested_payload: dict[str, Any]) -> bool:
    payload_kind = str(suggested_payload.get("kind") or "")
    if not suggested_action or not payload_kind:
        return False
    if suggested_action == "review_carefully":
        return payload_kind == "change_decision"
    if "relink" in suggested_action:
        return "family_relink" in payload_kind
    if "alias" in suggested_action:
        return "label_learning" in payload_kind
    return True


def _execution_mode_matches_payload(*, execution_mode: str, suggested_payload: dict[str, Any]) -> bool:
    payload_kind = str(suggested_payload.get("kind") or "")
    if payload_kind in {"change_decision", "run_source_sync", "family_relink_commit", "label_learning_add_alias_commit", "proposal_edit_commit"}:
        return execution_mode == "approval_ticket_required"
    return execution_mode == "web_only"


def _risk_label_matches_context(*, risk_level: str, context: dict[str, Any]) -> bool:
    if not risk_level:
        return False
    for payload in (context, context.get("recommended_next_action") if isinstance(context.get("recommended_next_action"), dict) else None):
        if isinstance(payload, dict):
            candidate = str(payload.get("risk_level") or "")
            if candidate:
                return candidate == risk_level
    return True


def _language_matches_texts(*, language_code: str, texts: tuple[str, str]) -> bool:
    if language_code == "zh-CN":
        return any("\u4e00" <= ch <= "\u9fff" for text in texts for ch in text)
    return all(not any("\u4e00" <= ch <= "\u9fff" for ch in text) for text in texts if text)


def _forbidden_action_absent(*, texts: tuple[str, str]) -> bool:
    joined = " ".join(texts).lower()
    forbidden = (
        "directly execute",
        "already executed",
        "write canonical state",
        "skip approval",
        "bypass approval",
    )
    return not any(item in joined for item in forbidden)


def _quality_score(*, text: str, long_limit: int) -> float:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return 0.0
    if len(normalized) > long_limit:
        return 0.7
    return 1.0


def _judge_narrative(
    *,
    db,
    judge_mode: str,
    payload: dict[str, Any],
    summary: str,
    reason: str,
    deterministic_flags: dict[str, bool],
) -> dict[str, Any]:
    if judge_mode in {"off", "deterministic"}:
        return {
            "judge_available": False,
            "summary_naturalness_score": None,
            "reason_naturalness_score": None,
            "boundary_explanation_score": None,
            "judge_language_match": None,
            "judge_overall_score": None,
            "judge_notes": [],
            "judge_usage": None,
            "judge_cost": None,
        }
    try:
        result = invoke_llm_json(
            db,
            invoke_request=LlmInvokeRequest(
                task_name="agent_proposal_quality_judge",
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                user_payload={
                    "proposal_type": payload.get("proposal_type"),
                    "target_kind": payload.get("target_kind"),
                    "target_id": payload.get("target_id"),
                    "risk_level": payload.get("risk_level"),
                    "suggested_action": payload.get("suggested_action"),
                    "execution_mode": payload.get("execution_mode"),
                    "language_code": payload.get("language_code"),
                    "summary": summary,
                    "reason": reason,
                    "deterministic_flags": deterministic_flags,
                },
                output_schema_name="AgentProposalNarrativeJudgeResponse",
                output_schema_json={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "summary_naturalness_score": {"type": "number"},
                        "reason_naturalness_score": {"type": "number"},
                        "boundary_explanation_score": {"type": "number"},
                        "language_match": {"type": "boolean"},
                        "notes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "summary_naturalness_score",
                        "reason_naturalness_score",
                        "boundary_explanation_score",
                        "language_match",
                        "notes",
                    ],
                },
                profile_family="agent",
                source_id=None,
                request_id=None,
                source_provider=None,
                temperature=0.0,
                session_cache_mode="disable",
            ),
        )
        judge = result.json_object if isinstance(result.json_object, dict) else {}
        usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
        cost = estimate_llm_usage_cost(
            provider_id=result.provider_id,
            vendor=result.vendor,
            model=result.model,
            protocol=result.protocol,
            usage=usage,
        )
        summary_score = max(0.0, min(float(judge.get("summary_naturalness_score") or 0), 1.0))
        reason_score = max(0.0, min(float(judge.get("reason_naturalness_score") or 0), 1.0))
        boundary_score = max(0.0, min(float(judge.get("boundary_explanation_score") or 0), 1.0))
        judge_overall_score = round((summary_score + reason_score + boundary_score) / 3, 4)
        return {
            "judge_available": True,
            "summary_naturalness_score": summary_score,
            "reason_naturalness_score": reason_score,
            "boundary_explanation_score": boundary_score,
            "judge_language_match": bool(judge.get("language_match")),
            "judge_overall_score": judge_overall_score,
            "judge_notes": list(judge.get("notes") or []),
            "judge_usage": {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            },
            "judge_cost": cost,
        }
    except Exception:
        return {
            "judge_available": False,
            "summary_naturalness_score": None,
            "reason_naturalness_score": None,
            "boundary_explanation_score": None,
            "judge_language_match": None,
            "judge_overall_score": None,
            "judge_notes": [],
            "judge_usage": None,
            "judge_cost": None,
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _avg(values) -> float | None:
    rows = list(values)
    if not rows:
        return None
    return round(sum(rows) / len(rows), 4)


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2%}"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
