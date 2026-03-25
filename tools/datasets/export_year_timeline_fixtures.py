from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.modules.runtime.connectors.ics_delta.diff import build_ics_delta
from app.modules.runtime.connectors.ics_delta.parser import parse_ics_snapshot
from tools.datasets.year_timeline_background_stream import (
    DEFAULT_BACKGROUND_SEED,
    build_background_email_samples,
    build_year_timeline_background_stream,
)
from tools.datasets.year_timeline_full_sim import (
    FULL_SIM_BUCKET,
    build_full_sim_academic_noise_set,
    build_full_sim_bucket_manifest,
    build_full_sim_false_positive_bait_set,
    build_full_sim_finals_window_set,
    build_full_sim_mixed_regression_set,
    build_full_sim_quarter_start_set,
    build_full_sim_smoke_set,
    build_full_sim_wrapper_heavy_set,
    compose_year_timeline_full_sim,
)
from tools.datasets.year_timeline_scenarios import build_year_timeline_manifest

EMAIL_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool"
ICS_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "ics_timeline"
MIXED_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "year_timeline_mixed"

EMAIL_BUCKET = "year_timeline_gmail"
EMAIL_DERIVED_SMOKE = "year_timeline_smoke_24"
EMAIL_DERIVED_DIRECTIVE = "year_timeline_directive_48"
EMAIL_DERIVED_ALIAS = "year_timeline_alias_hard_48"
EMAIL_DERIVED_FAMILY = "year_timeline_family_alias_48"
EMAIL_DERIVED_PROF_TA = "year_timeline_prof_ta_conflict_48"
EMAIL_DERIVED_CANVAS_WRAPPER = "year_timeline_canvas_wrapper_48"
EMAIL_DERIVED_JUNK_HEAVY = "year_timeline_junk_heavy_48"
FULL_SIM_DERIVED_SMOKE = "year_timeline_full_sim_smoke_96"
FULL_SIM_DERIVED_FALSE_POSITIVE = "year_timeline_full_sim_false_positive_bait_96"
FULL_SIM_DERIVED_ACADEMIC_NOISE = "year_timeline_full_sim_academic_noise_96"
FULL_SIM_DERIVED_WRAPPER_HEAVY = "year_timeline_full_sim_wrapper_heavy_96"
FULL_SIM_DERIVED_QUARTER_START = "year_timeline_full_sim_quarter_start_64"
FULL_SIM_DERIVED_FINALS_WINDOW = "year_timeline_full_sim_finals_window_64"
FULL_SIM_DERIVED_MIXED_REGRESSION = "year_timeline_full_sim_mixed_regression_192"

ICS_SCENARIO_IDS = {
    "WI26": "year-timeline-wi26",
    "SP26": "year-timeline-sp26",
    "SU26": "year-timeline-su26",
    "FA26": "year-timeline-fa26",
}
ICS_DERIVED_SMOKE = "year_timeline_smoke_16"
ICS_DERIVED_CHANGE_HEAVY = "year_timeline_change_heavy_24"
ICS_DERIVED_REMOVED_FOCUS = "year_timeline_removed_focus_16"
ICS_DERIVED_CALENDAR_FIRST = "year_timeline_calendar_first_16"
ICS_DERIVED_EMAIL_FIRST = "year_timeline_email_first_16"

MIXED_DERIVED_CROSS_CHANNEL_LAG = "year_timeline_cross_channel_lag_24"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export year timeline manifest into offline email-pool and ICS-timeline fixtures.")
    parser.add_argument(
        "--manifest",
        default="data/synthetic/year_timeline_demo/year_timeline_manifest.json",
        help="Year timeline manifest path. If missing, rebuild from defaults.",
    )
    parser.add_argument(
        "--target",
        choices=["all", "email", "ics", "mixed"],
        default="all",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_or_build_manifest(Path(args.manifest))
    if args.target in {"all", "email"}:
        export_email_pool(manifest)
    if args.target in {"all", "ics"}:
        export_ics_timeline(manifest)
    if args.target in {"all", "mixed"}:
        export_mixed_derived_sets(manifest)


def load_or_build_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    manifest = build_year_timeline_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return manifest.to_dict()


def export_email_pool(manifest: dict[str, Any]) -> None:
    samples = build_email_samples(manifest)
    write_email_bucket(
        bucket=EMAIL_BUCKET,
        samples=samples,
        manifest_payload={
            "bucket": EMAIL_BUCKET,
            "generated_at": now_utc_iso(),
            "source_manifest": "data/synthetic/year_timeline_demo/year_timeline_manifest.json",
            "sample_count": len(samples),
            "expected_mode_breakdown": count_by_key(samples, "expected_mode"),
            "actor_role_breakdown": count_by_key(samples, "actor_role"),
            "channel_timing_breakdown": count_by_key(samples, "channel_timing_mode"),
            "notes": "Generated from year_timeline_demo manifest for long-range Gmail parser evaluation.",
        },
        readme_lines=[
            "# Email Pool Bucket: `year_timeline_gmail`",
            "",
            "- Generated from `data/synthetic/year_timeline_demo/year_timeline_manifest.json`.",
            "- Covers a one-year synthetic Gmail timeline with actor-role realism, cross-channel lag, and junk-heavy wrappers.",
            "- Use with `scripts/process_local_email_pool.py --bucket year_timeline_gmail`.",
            "",
        ],
    )
    update_email_library_catalog_entry(
        bucket=EMAIL_BUCKET,
        sample_count=len(samples),
        source_kind="synthetic_year_timeline",
        label_properties=[
            "expected_mode",
            "expected_record_type",
            "expected_semantic_event_draft",
            "expected_directive",
            "hard_case_tags",
            "actor_role",
            "channel_timing_mode",
            "message_intent",
            "junk_profile",
            "prefilter_expected_route",
            "prefilter_reason_family",
            "prefilter_target_class",
        ],
        best_use=[
            "long-range mixed Gmail regression",
            "directive and alias-hard evaluation",
            "role realism and cross-channel lag evaluation",
        ],
    )
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_SMOKE}.json", build_email_derived_smoke(samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_DIRECTIVE}.json", build_email_derived_directive(samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_ALIAS}.json", build_email_derived_alias(samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_FAMILY}.json", build_email_derived_family(samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_PROF_TA}.json", build_email_derived_prof_ta(samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_CANVAS_WRAPPER}.json", build_email_derived_canvas_wrapper(samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{EMAIL_DERIVED_JUNK_HEAVY}.json", build_email_derived_junk_heavy(samples))

    background_stream = build_year_timeline_background_stream(manifest=manifest, seed=DEFAULT_BACKGROUND_SEED)
    background_samples = build_background_email_samples(manifest=manifest, seed=DEFAULT_BACKGROUND_SEED)
    full_sim_samples = compose_year_timeline_full_sim(core_samples=samples, background_samples=background_samples)

    background_manifest_path = REPO_ROOT / "data" / "synthetic" / "year_timeline_demo" / "year_timeline_background_stream.json"
    background_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    background_manifest_path.write_text(json.dumps(background_stream.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    full_sim_bucket_manifest = {
        **build_full_sim_bucket_manifest(full_sim_samples),
        "generated_at": now_utc_iso(),
        "source_manifest": "data/synthetic/year_timeline_demo/year_timeline_manifest.json",
        "background_manifest": "data/synthetic/year_timeline_demo/year_timeline_background_stream.json",
        "expected_mode_breakdown": count_by_key(full_sim_samples, "expected_mode"),
    }
    full_sim_manifest_path = REPO_ROOT / "data" / "synthetic" / "year_timeline_demo" / "year_timeline_full_sim_manifest.json"
    full_sim_manifest_path.write_text(json.dumps(full_sim_bucket_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_email_bucket(
        bucket=FULL_SIM_BUCKET,
        samples=full_sim_samples,
        manifest_payload=full_sim_bucket_manifest,
        readme_lines=[
            "# Email Pool Bucket: `year_timeline_full_sim`",
            "",
            "- Generated by composing the core year timeline bucket with a deterministic background inbox stream.",
            "- Monitored course mail remains intact but becomes a minority inside a full mailbox stream.",
            "- Use with `scripts/process_local_email_pool.py --bucket year_timeline_full_sim`.",
            "",
        ],
    )
    update_email_library_catalog_entry(
        bucket=FULL_SIM_BUCKET,
        sample_count=len(full_sim_samples),
        source_kind="synthetic_year_timeline_full_sim",
        label_properties=[
            "expected_mode",
            "expected_record_type",
            "expected_semantic_event_draft",
            "expected_directive",
            "full_sim_layer",
            "background_category",
            "background_group",
            "background_sender_role",
            "message_structure",
            "background_topic",
            "bait_terms",
            "is_false_positive_bait",
            "prefilter_expected_route",
            "prefilter_reason_family",
            "prefilter_target_class",
            "prefilter_should_match_course_token",
            "prefilter_sender_strength",
        ],
        best_use=[
            "prefilter precision evaluation",
            "false-positive resistance evaluation",
            "full inbox parser robustness",
        ],
    )
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_SMOKE}.json", build_full_sim_smoke_set(full_sim_samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_FALSE_POSITIVE}.json", build_full_sim_false_positive_bait_set(full_sim_samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_ACADEMIC_NOISE}.json", build_full_sim_academic_noise_set(full_sim_samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_WRAPPER_HEAVY}.json", build_full_sim_wrapper_heavy_set(full_sim_samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_QUARTER_START}.json", build_full_sim_quarter_start_set(full_sim_samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_FINALS_WINDOW}.json", build_full_sim_finals_window_set(full_sim_samples))
    write_json(EMAIL_ROOT / "derived_sets" / f"{FULL_SIM_DERIVED_MIXED_REGRESSION}.json", build_full_sim_mixed_regression_set(full_sim_samples))


def write_email_bucket(
    *,
    bucket: str,
    samples: list[dict[str, Any]],
    manifest_payload: dict[str, Any],
    readme_lines: list[str],
) -> None:
    bucket_dir = EMAIL_ROOT / bucket
    bucket_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(bucket_dir / "samples.jsonl", samples)
    write_json(bucket_dir / "manifest.json", manifest_payload)
    (bucket_dir / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")


def export_ics_timeline(manifest: dict[str, Any]) -> None:
    scenarios_root = ICS_ROOT / "scenarios"
    scenarios_root.mkdir(parents=True, exist_ok=True)
    scenario_summaries: list[dict[str, Any]] = []
    all_transitions: list[dict[str, Any]] = []
    heavy_candidates: list[tuple[int, dict[str, str]]] = []
    removed_candidates: list[dict[str, str]] = []

    for phase in manifest.get("plans", []):
        if not isinstance(phase, dict):
            continue
        phase_label = str(phase.get("phase_label") or "")
        scenario_id = ICS_SCENARIO_IDS[phase_label]
        scenario_dir = scenarios_root / scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)

        batches = [row for row in phase.get("batches", []) if isinstance(row, dict)]
        round_files = ["round-00.ics"] + [f"round-{index:02d}.ics" for index in range(1, len(batches) + 1)]
        (scenario_dir / "round-00.ics").write_text(render_ics_calendar([]), encoding="utf-8")
        for index, batch in enumerate(batches, start=1):
            events = [row for row in batch.get("ics_events", []) if isinstance(row, dict)]
            (scenario_dir / f"round-{index:02d}.ics").write_text(render_ics_calendar(events), encoding="utf-8")

        transitions: list[dict[str, Any]] = []
        for index in range(1, len(batches) + 1):
            batch = batches[index - 1]
            events = [row for row in batch.get("ics_events", []) if isinstance(row, dict)]
            event_by_uid = {str(row.get("entity_uid") or ""): row for row in events if str(row.get("entity_uid") or "")}
            from_round = f"round-{index-1:02d}"
            to_round = f"round-{index:02d}"
            before_path = scenario_dir / f"{from_round}.ics"
            after_path = scenario_dir / f"{to_round}.ics"
            before_snapshot = parse_ics_snapshot(content=before_path.read_bytes())
            delta = build_ics_delta(
                content=after_path.read_bytes(),
                previous_fingerprints={key: component.fingerprint for key, component in before_snapshot.components.items()},
            )
            changed_event_metadata = []
            for row in delta.changed_components:
                event = event_by_uid.get(str(row["external_event_id"]))
                if event is None:
                    continue
                changed_event_metadata.append(
                    {
                        "external_event_id": row["external_event_id"],
                        "channel_timing_mode": event.get("channel_timing_mode"),
                        "ics_change_kind": event.get("ics_change_kind"),
                        "hard_case_tags": list(event.get("hard_case_tags") or []),
                    }
                )
            transition = {
                "transition_id": f"{from_round}__to__{to_round}",
                "from_round": from_round,
                "to_round": to_round,
                "expected_changed_components": [
                    {
                        "component_key": row["component_key"],
                        "external_event_id": row["external_event_id"],
                    }
                    for row in delta.changed_components
                ],
                "expected_removed_component_keys": list(delta.removed_component_keys),
                "expected_changed_count": len(delta.changed_components),
                "expected_removed_count": len(delta.removed_component_keys),
                "channel_timing_breakdown": count_by_key(changed_event_metadata, "channel_timing_mode"),
                "ics_change_kind_breakdown": count_by_key(changed_event_metadata, "ics_change_kind"),
                "hard_case_tags": sorted({tag for row in changed_event_metadata for tag in row["hard_case_tags"]}),
            }
            transitions.append(transition)
            pointer = {"scenario_id": scenario_id, "transition_id": transition["transition_id"]}
            all_transitions.append({**pointer, **transition})
            heavy_candidates.append((transition["expected_changed_count"], pointer))
            if transition["expected_removed_count"] > 0:
                removed_candidates.append(pointer)

        write_json(
            scenario_dir / "manifest.json",
            {
                "scenario_id": scenario_id,
                "round_files": round_files,
                "transition_count": len(transitions),
                "transitions": transitions,
            },
        )
        (scenario_dir / "notes.md").write_text(
            "\n".join(
                [
                    f"# {scenario_id}",
                    "",
                    f"- Phase: {phase_label}",
                    f"- Courses: {', '.join(str(row) for row in phase.get('courses', []))}",
                    f"- Batches: {len(batches)}",
                    f"- Batch size: {manifest['batch_size']}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        scenario_summaries.append(
            {
                "scenario_id": scenario_id,
                "round_count": len(round_files),
                "transition_count": len(transitions),
                "notes_file": str((scenario_dir / "notes.md").relative_to(REPO_ROOT)),
            }
        )

    update_ics_library_catalog(scenario_summaries=scenario_summaries)
    write_json(ICS_ROOT / "derived_sets" / f"{ICS_DERIVED_SMOKE}.json", build_ics_smoke_set(all_transitions))
    write_json(ICS_ROOT / "derived_sets" / f"{ICS_DERIVED_CHANGE_HEAVY}.json", build_ics_change_heavy_set(heavy_candidates))
    write_json(ICS_ROOT / "derived_sets" / f"{ICS_DERIVED_REMOVED_FOCUS}.json", build_ics_removed_focus_set(removed_candidates, all_transitions))
    write_json(ICS_ROOT / "derived_sets" / f"{ICS_DERIVED_CALENDAR_FIRST}.json", build_ics_calendar_first_set(all_transitions))
    write_json(ICS_ROOT / "derived_sets" / f"{ICS_DERIVED_EMAIL_FIRST}.json", build_ics_email_first_set(all_transitions))


def export_mixed_derived_sets(manifest: dict[str, Any]) -> None:
    derived_root = MIXED_ROOT / "derived_sets"
    derived_root.mkdir(parents=True, exist_ok=True)
    bundles: list[dict[str, Any]] = []
    for phase in manifest.get("plans", []):
        if not isinstance(phase, dict):
            continue
        phase_label = str(phase.get("phase_label") or "")
        scenario_id = ICS_SCENARIO_IDS.get(phase_label)
        if scenario_id is None:
            continue
        semester = int(phase.get("semester") or 0)
        for batch in phase.get("batches", []):
            if not isinstance(batch, dict):
                continue
            batch_no = int(batch.get("batch") or 0)
            lag_samples = []
            lag_modes: set[str] = set()
            for row in batch.get("gmail_messages", []):
                if not isinstance(row, dict):
                    continue
                mode = str(row.get("channel_timing_mode") or "")
                if mode in {"email_first", "canvas_plus_1_batch", "email_plus_1_batch"}:
                    lag_samples.append(str(row.get("message_id") or ""))
                    lag_modes.add(mode)
            for row in batch.get("ics_events", []):
                if not isinstance(row, dict):
                    continue
                mode = str(row.get("channel_timing_mode") or "")
                if mode in {"canvas_first", "calendar_only", "canvas_plus_1_batch", "email_plus_1_batch"}:
                    lag_modes.add(mode)
            if not lag_samples and not lag_modes:
                continue
            bundles.append(
                {
                    "semester": semester,
                    "batch": batch_no,
                    "scenario_id": scenario_id,
                    "transition_id": f"round-{batch_no-1:02d}__to__round-{batch_no:02d}",
                    "email_sample_ids": lag_samples[:6],
                    "lag_modes": sorted(lag_modes),
                }
            )
    bundles = bundles[:24]
    write_json(
        derived_root / f"{MIXED_DERIVED_CROSS_CHANNEL_LAG}.json",
        {
            "name": MIXED_DERIVED_CROSS_CHANNEL_LAG,
            "description": "Batches where Gmail and ICS intentionally drift by channel timing or sync lag.",
            "bundles": bundles,
        },
    )
    write_json(
        MIXED_ROOT / "library_catalog.json",
        {
            "generated_at": now_utc_iso(),
            "derived_sets_dir": "tests/fixtures/private/year_timeline_mixed/derived_sets",
            "derived_sets": [MIXED_DERIVED_CROSS_CHANNEL_LAG],
        },
    )


def build_email_samples(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for phase in manifest.get("plans", []):
        if not isinstance(phase, dict):
            continue
        phase_label = str(phase.get("phase_label") or "")
        quarter, year2 = parse_phase_label(str(phase.get("phase_label") or ""))
        for batch in phase.get("batches", []):
            if not isinstance(batch, dict):
                continue
            for message in batch.get("gmail_messages", []):
                if not isinstance(message, dict):
                    continue
                kind = str(message.get("message_kind") or "admin_noise")
                expected_mode, expected_record_type = expected_mode_for_kind(kind)
                sample = {
                    "sample_id": str(message["message_id"]),
                    "sample_source": "synthetic.year_timeline.gmail",
                    "message_id": str(message["message_id"]),
                    "thread_id": str(message["thread_id"]),
                    "subject": str(message["subject"]),
                    "from_header": str(message["from_header"]),
                    "snippet": build_snippet(str(message["body_text"])),
                    "body_text": str(message["body_text"]),
                    "internal_date": str(message["internal_date"]),
                    "label_ids": list(message.get("label_ids") or []),
                    "collection_bucket": EMAIL_BUCKET,
                    "notes": ", ".join(
                        [
                            str(message.get("actor_role") or ""),
                            str(message.get("channel_timing_mode") or ""),
                            *(str(tag) for tag in message.get("hard_case_tags") or []),
                        ]
                    ).strip(", "),
                    "message_kind": kind,
                    "expected_mode": expected_mode,
                    "expected_record_type": expected_record_type,
                    "expected_semantic_event_draft": None,
                    "expected_directive": None,
                    "hard_case_tags": list(message.get("hard_case_tags") or []),
                    "actor_role": message.get("actor_role"),
                    "authority_level": message.get("authority_level"),
                    "channel_timing_mode": message.get("channel_timing_mode"),
                    "message_intent": message.get("message_intent"),
                    "junk_profile": message.get("junk_profile"),
                    "course_archetype": message.get("course_archetype"),
                    "teaching_style": message.get("teaching_style"),
                    "channel_behavior": message.get("channel_behavior"),
                    "course_label": message["course"]["label"],
                    "phase_label": phase_label,
                    "week_stage": message.get("week_stage"),
                }
                if expected_mode == "atomic":
                    sample["expected_semantic_event_draft"] = {
                        "course_dept": message["course"]["dept"],
                        "course_number": message["course"]["number"],
                        "course_suffix": message["course"]["suffix"],
                        "course_quarter": quarter,
                        "course_year2": year2,
                        "raw_type": message["family_label"],
                        "event_name": message.get("canonical_event_name") or f"{message['family_label']} {message['ordinal']}",
                        "ordinal": message["ordinal"],
                        "due_date": str(message["due_iso"])[:10],
                        "due_time": normalize_due_time(str(message["due_iso"])),
                        "time_precision": "datetime",
                        "confidence": 0.96,
                        "evidence": build_evidence_text(message),
                    }
                elif expected_mode == "directive":
                    sample["expected_directive"] = {
                        "outcome": "directive",
                        "selector": {
                            "course_dept": message["course"]["dept"],
                            "course_number": message["course"]["number"],
                            "course_suffix": message["course"]["suffix"],
                            "course_quarter": quarter,
                            "course_year2": year2,
                            "family_hint": message["family_label"],
                            "raw_type_hint": message["family_label"],
                            "scope_mode": message.get("directive_scope_mode") or "all_matching",
                            "ordinal_list": list(message.get("selector_ordinals") or []) if message.get("directive_scope_mode") == "ordinal_list" else [],
                            "ordinal_range_start": (
                                min(message.get("selector_ordinals") or []) if message.get("directive_scope_mode") == "ordinal_range" and message.get("selector_ordinals") else None
                            ),
                            "ordinal_range_end": (
                                max(message.get("selector_ordinals") or []) if message.get("directive_scope_mode") == "ordinal_range" and message.get("selector_ordinals") else None
                            ),
                            "current_due_weekday": message.get("current_due_weekday"),
                            "applies_to_future_only": True,
                        },
                        "mutation": {
                            "move_weekday": message.get("move_weekday"),
                            "set_due_date": message.get("set_due_date"),
                        },
                        "confidence": 0.97,
                        "evidence": build_evidence_text(message),
                    }
                sample.update(prefilter_metadata_for_core_message(message=message, expected_mode=expected_mode))
                samples.append(sample)
    return samples


def build_email_derived_smoke(samples: list[dict[str, Any]]) -> dict[str, Any]:
    atomic_new = [
        row["sample_id"]
        for row in samples
        if row.get("message_kind") == "atomic_new" and row.get("actor_role") != "canvas_wrapper" and "role_authority_conflict" not in row.get("hard_case_tags", [])
    ]
    atomic_change = [
        row["sample_id"]
        for row in samples
        if row.get("message_kind") == "atomic_change" and row.get("actor_role") != "canvas_wrapper" and "role_authority_conflict" not in row.get("hard_case_tags", [])
    ]
    directives = [row["sample_id"] for row in samples if row["expected_mode"] == "directive"]
    unknown = [row["sample_id"] for row in samples if row["expected_mode"] == "unknown" and row.get("message_kind") == "reminder_noise"]
    selected = atomic_new[:8] + atomic_change[:8] + directives[:4] + unknown[:4]
    return {
        "name": EMAIL_DERIVED_SMOKE,
        "description": "Balanced one-year local Gmail smoke set with readable but realistic wording.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: selected},
    }


def build_email_derived_directive(samples: list[dict[str, Any]]) -> dict[str, Any]:
    directives = [row["sample_id"] for row in samples if row["expected_mode"] == "directive"][:48]
    return {
        "name": EMAIL_DERIVED_DIRECTIVE,
        "description": "Directive-heavy one-year local Gmail set.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: directives},
    }


def build_email_derived_alias(samples: list[dict[str, Any]]) -> dict[str, Any]:
    alias_rows = [
        row["sample_id"]
        for row in samples
        if any(tag in {"single_item_all_sections", "suffix_sensitive", "alias_hw", "alias_problem_set", "relative_time_phrase", "absolute_human_phrase"} for tag in row.get("hard_case_tags", []))
    ][:48]
    return {
        "name": EMAIL_DERIVED_ALIAS,
        "description": "Alias-heavy and ambiguity-focused one-year local Gmail set.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: alias_rows},
    }


def build_email_derived_family(samples: list[dict[str, Any]]) -> dict[str, Any]:
    family_rows = [
        row["sample_id"]
        for row in samples
        if row.get("expected_mode") == "atomic"
        and any(tag in {"single_item_all_sections", "suffix_sensitive", "alias_hw", "alias_problem_set"} for tag in row.get("hard_case_tags", []))
    ][:48]
    return {
        "name": EMAIL_DERIVED_FAMILY,
        "description": "Family merge and alias-learning focused one-year Gmail set.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: family_rows},
    }


def build_email_derived_prof_ta(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        row["sample_id"]
        for row in samples
        if row.get("actor_role") in {"professor", "ta"}
        and (
            row.get("message_intent") in {"pre_notice", "confirmation"}
            or any(tag in {"ta_pre_notice_then_professor_confirm", "role_authority_conflict"} for tag in row.get("hard_case_tags", []))
        )
    ]
    if len(rows) < 48:
        seen = set(rows)
        fallback = [
            row["sample_id"]
            for row in samples
            if row.get("actor_role") in {"professor", "ta"} and row["sample_id"] not in seen
        ]
        rows.extend(fallback[: 48 - len(rows)])
    return {
        "name": EMAIL_DERIVED_PROF_TA,
        "description": "Professor vs TA authority conflict and confirmation set.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: rows[:48]},
    }


def build_email_derived_canvas_wrapper(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        row["sample_id"]
        for row in samples
        if row.get("actor_role") == "canvas_wrapper" or "canvas_wrapper_with_signal_buried" in row.get("hard_case_tags", [])
    ]
    if len(rows) < 48:
        seen = set(rows)
        fallback = [
            row["sample_id"]
            for row in samples
            if (row.get("junk_profile") == "lms_wrapper" or row.get("channel_behavior") in {"canvas_first", "email_plus_1_batch"})
            and row["sample_id"] not in seen
        ]
        rows.extend(fallback[: 48 - len(rows)])
    return {
        "name": EMAIL_DERIVED_CANVAS_WRAPPER,
        "description": "Canvas wrapper dominated set with buried signals and wrapper noise.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: rows[:48]},
    }


def build_email_derived_junk_heavy(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        row["sample_id"]
        for row in samples
        if row.get("junk_profile") in {"lms_wrapper", "department_bureaucracy", "faq_digest", "alias_broadcast"}
        or len(str(row.get("body_text") or "")) >= 420
    ][:48]
    return {
        "name": EMAIL_DERIVED_JUNK_HEAVY,
        "description": "Junk-heavy year timeline Gmail set with wrappers, policy text, and admin clutter.",
        "sample_ids_by_bucket": {EMAIL_BUCKET: rows},
    }


def update_email_library_catalog_entry(
    *,
    bucket: str,
    sample_count: int,
    source_kind: str,
    label_properties: list[str],
    best_use: list[str],
) -> None:
    path = EMAIL_ROOT / "library_catalog.json"
    payload: dict[str, Any]
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {"version": 1, "buckets": {}}
    payload["generated_at"] = now_utc_iso()
    payload.setdefault("buckets", {})
    payload["buckets"][bucket] = {
        "input_kind": "gmail_message",
        "source_kind": source_kind,
        "sample_count": sample_count,
        "label_properties": label_properties,
        "best_use": best_use,
    }
    write_json(path, payload)


def update_ics_library_catalog(*, scenario_summaries: list[dict[str, Any]]) -> None:
    catalog_path = ICS_ROOT / "library_catalog.json"
    merged_by_id: dict[str, dict[str, Any]] = {}
    if catalog_path.exists():
        existing_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        existing_scenarios = [row for row in existing_catalog.get("scenarios", []) if isinstance(row, dict)]
        merged_by_id.update({str(row.get("scenario_id") or ""): row for row in existing_scenarios if str(row.get("scenario_id") or "")})
    for row in scenario_summaries:
        merged_by_id[str(row["scenario_id"])] = row
    write_json(
        catalog_path,
        {
            "version": 1,
            "library_kind": "local_ics_timeline_library",
            "generated_at": now_utc_iso(),
            "coverage": {"gmail": False, "ics": True},
            "notes": [
                "This library stores coherent Canvas-like ICS timeline scenarios for local delta and parser testing.",
                "Year timeline scenarios are generated from the one-year year_timeline_demo manifest.",
                "Delta truth is derived programmatically from adjacent round files.",
            ],
            "scenarios_dir": "tests/fixtures/private/ics_timeline/scenarios",
            "derived_sets_dir": "tests/fixtures/private/ics_timeline/derived_sets",
            "scenario_count": len(merged_by_id),
            "scenarios": sorted(merged_by_id.values(), key=lambda row: str(row.get("scenario_id") or "")),
        },
    )


def build_ics_smoke_set(all_transitions: list[dict[str, Any]]) -> dict[str, Any]:
    selected: list[dict[str, str]] = []
    for scenario_id in ICS_SCENARIO_IDS.values():
        scenario_rows = [row for row in all_transitions if row["scenario_id"] == scenario_id]
        selected.extend([{"scenario_id": row["scenario_id"], "transition_id": row["transition_id"]} for row in scenario_rows[:1] + scenario_rows[3:4] + scenario_rows[7:8] + scenario_rows[11:12]])
    return {
        "name": ICS_DERIVED_SMOKE,
        "description": "One-year ICS mixed smoke set.",
        "transitions": selected[:16],
    }


def build_ics_change_heavy_set(heavy_candidates: list[tuple[int, dict[str, str]]]) -> dict[str, Any]:
    ordered = [pointer for _count, pointer in sorted(heavy_candidates, key=lambda item: (-item[0], item[1]["scenario_id"], item[1]["transition_id"]))[:24]]
    return {
        "name": ICS_DERIVED_CHANGE_HEAVY,
        "description": "One-year ICS change-heavy transitions.",
        "transitions": ordered,
    }


def build_ics_removed_focus_set(removed_candidates: list[dict[str, str]], all_transitions: list[dict[str, Any]]) -> dict[str, Any]:
    selected = list(removed_candidates[:16])
    if len(selected) < 16:
        seen = {(row["scenario_id"], row["transition_id"]) for row in selected}
        for row in all_transitions:
            key = (row["scenario_id"], row["transition_id"])
            if key in seen:
                continue
            selected.append({"scenario_id": row["scenario_id"], "transition_id": row["transition_id"]})
            seen.add(key)
            if len(selected) == 16:
                break
    return {
        "name": ICS_DERIVED_REMOVED_FOCUS,
        "description": "One-year ICS transitions with removals emphasized.",
        "transitions": selected,
    }


def build_ics_calendar_first_set(all_transitions: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [
        {"scenario_id": row["scenario_id"], "transition_id": row["transition_id"]}
        for row in all_transitions
        if any(mode in {"canvas_first", "email_plus_1_batch", "calendar_only"} for mode in row.get("channel_timing_breakdown", {}))
    ][:16]
    return {
        "name": ICS_DERIVED_CALENDAR_FIRST,
        "description": "Transitions where calendar inventory or calendar-only changes lead the signal.",
        "transitions": selected,
    }


def build_ics_email_first_set(all_transitions: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [
        {"scenario_id": row["scenario_id"], "transition_id": row["transition_id"]}
        for row in all_transitions
        if any(mode in {"email_first", "canvas_plus_1_batch"} for mode in row.get("channel_timing_breakdown", {}))
    ][:16]
    return {
        "name": ICS_DERIVED_EMAIL_FIRST,
        "description": "Transitions whose items were pre-announced in email before the structured calendar view caught up.",
        "transitions": selected,
    }


def render_ics_calendar(events: list[dict[str, Any]]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CalendarDIFF//YearTimeline//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        due_iso = str(event.get("due_iso") or "")
        if not due_iso:
            continue
        due_at = datetime.fromisoformat(due_iso)
        end_at = due_at + timedelta(hours=1)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"DTSTAMP:{due_at.strftime('%Y%m%dT%H%M%SZ')}",
                f"UID:{event['entity_uid']}",
                f"DTSTART:{due_at.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{end_at.strftime('%Y%m%dT%H%M%SZ')}",
                "CLASS:PUBLIC",
                f"DESCRIPTION:Course: {event['course']['label']}\\nFamily: {event['family_label']}\\nOrdinal: {event['ordinal']}\\nPhase: {event['phase_label']}",
                "SEQUENCE:0",
                f"SUMMARY:{event['title']}",
                f"URL;VALUE=URI:https://calendar-diff.synthetic/{event['event_id']}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def parse_phase_label(value: str) -> tuple[str | None, int | None]:
    cleaned = value.strip().upper()
    if len(cleaned) < 4:
        return None, None
    quarter = cleaned[:2]
    year_token = cleaned[2:]
    return quarter, int(year_token) if year_token.isdigit() else None


def expected_mode_for_kind(kind: str) -> tuple[str, str | None]:
    if kind in {"atomic_new", "atomic_change"}:
        return "atomic", "gmail.message.extracted"
    if kind == "directive":
        return "directive", "gmail.directive.extracted"
    return "unknown", None


def prefilter_metadata_for_core_message(*, message: dict[str, Any], expected_mode: str) -> dict[str, Any]:
    actor_role = str(message.get("actor_role") or "")
    kind = str(message.get("message_kind") or "")
    if expected_mode in {"atomic", "directive"}:
        reason_family = "target_course_signal"
        target_class = "target_signal"
        expected_route = "parse"
    else:
        reason_family = {
            "reminder_noise": "target_course_reminder_noise",
            "lab_noise": "target_course_lab_noise",
            "admin_noise": "target_course_admin_noise",
        }.get(kind, "target_course_noise")
        target_class = "non_target"
        expected_route = "skip_unknown"
    return {
        "prefilter_expected_route": expected_route,
        "prefilter_reason_family": reason_family,
        "prefilter_target_class": target_class,
        "prefilter_should_match_course_token": True,
        "prefilter_sender_strength": prefilter_sender_strength_for_actor_role(actor_role),
        "prefilter_keyword_bait": [],
    }


def prefilter_sender_strength_for_actor_role(actor_role: str) -> str:
    if actor_role in {"professor", "course_staff_alias", "canvas_wrapper"}:
        return "strong"
    if actor_role in {"ta", "department_admin"}:
        return "medium"
    return "weak"


def normalize_due_time(value: str) -> str:
    return value[11:19]


def build_snippet(body_text: str, *, max_chars: int = 180) -> str:
    text = " ".join(body_text.strip().split())
    return text[:max_chars]


def build_evidence_text(message: dict[str, Any]) -> str:
    if message.get("set_due_date"):
        return f"{message['family_label']} {message.get('selector_ordinals') or ''} now due {message['set_due_date']}"
    if message.get("move_weekday"):
        return f"all future {message['family_label']} move to {message['move_weekday']}"
    if message.get("message_kind") == "atomic_change" and message.get("previous_due_iso"):
        return f"{message['canonical_event_name']} moved from {message['previous_due_iso']} to {message['due_iso']}"
    return str(message.get("due_iso") or "")


def count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        raw = row.get(key)
        normalized = str(raw) if raw is not None else "null"
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
