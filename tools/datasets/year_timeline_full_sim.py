from __future__ import annotations

from collections import defaultdict
from typing import Any

FULL_SIM_BUCKET = "year_timeline_full_sim"


def compose_year_timeline_full_sim(
    *,
    core_samples: list[dict[str, Any]],
    background_samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    mixed: list[dict[str, Any]] = []

    for row in core_samples:
        copied = dict(row)
        copied["collection_bucket"] = FULL_SIM_BUCKET
        copied["full_sim_layer"] = "core_course"
        copied["source_bucket"] = row.get("collection_bucket")
        mixed.append(copied)

    for row in background_samples:
        copied = dict(row)
        copied["collection_bucket"] = FULL_SIM_BUCKET
        copied.setdefault("full_sim_layer", "background_noise")
        copied["source_bucket"] = "background_stream"
        mixed.append(copied)

    mixed.sort(
        key=lambda row: (
            str(row.get("internal_date") or ""),
            0 if row.get("full_sim_layer") == "core_course" else 1,
            str(row.get("sample_id") or ""),
        )
    )
    return mixed


def build_full_sim_bucket_manifest(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_layer = _count_by_key(samples, "full_sim_layer")
    by_category = _count_by_key([row for row in samples if row.get("full_sim_layer") == "background_noise"], "background_category")
    by_group = _count_by_key([row for row in samples if row.get("full_sim_layer") == "background_noise"], "background_group")
    return {
        "bucket": FULL_SIM_BUCKET,
        "sample_count": len(samples),
        "layer_breakdown": by_layer,
        "background_category_breakdown": by_category,
        "background_group_breakdown": by_group,
        "prefilter_expected_route_breakdown": _count_by_key(samples, "prefilter_expected_route"),
        "prefilter_reason_family_breakdown": _count_by_key(samples, "prefilter_reason_family"),
        "prefilter_target_class_breakdown": _count_by_key(samples, "prefilter_target_class"),
        "phase_breakdown": _count_by_key(samples, "phase_label"),
    }


def build_full_sim_smoke_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    core = _select(samples, full_sim_layer="core_course")[:12]
    academic = _select(samples, background_group="academic_non_target")[:16]
    wrapper = _select(samples, background_group="wrapper_clutter")[:24]
    unrelated = _select(samples, background_group="unrelated_general")[:44]
    return _set_payload(
        name="year_timeline_full_sim_smoke_96",
        description="Representative mixed full-sim inbox sample.",
        sample_ids=core + academic + wrapper + unrelated,
    )


def build_full_sim_false_positive_bait_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    bait = [row["sample_id"] for row in samples if row.get("full_sim_layer") == "background_noise" and row.get("is_false_positive_bait")]
    return _set_payload(
        name="year_timeline_full_sim_false_positive_bait_96",
        description="False-positive bait messages with deadline-like or project-like wording but non-target semantics.",
        sample_ids=bait[:96],
    )


def build_full_sim_academic_noise_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    academic = [
        row["sample_id"]
        for row in samples
        if row.get("background_category") in {"academic_non_target", "lms_wrapper_noise"}
    ]
    return _set_payload(
        name="year_timeline_full_sim_academic_noise_96",
        description="Academic but non-target clutter including grade posts, lab logistics, office hours, and LMS wrappers.",
        sample_ids=academic[:96],
    )


def build_full_sim_wrapper_heavy_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    wrapper = [
        row["sample_id"]
        for row in samples
        if row.get("background_category") in {"newsletter", "calendar_wrapper", "lms_wrapper_noise"}
        or row.get("message_structure") in {"wrapper_quoted", "list_digest"}
    ]
    return _set_payload(
        name="year_timeline_full_sim_wrapper_heavy_96",
        description="Wrapper-heavy full-sim sample with digests, quoted wrappers, and LMS clutter.",
        sample_ids=wrapper[:96],
    )


def build_full_sim_quarter_start_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    quarter_start = [
        row["sample_id"]
        for row in samples
        if row.get("week_stage") == "setup_release" or row.get("season_tag") == "quarter-start"
    ]
    return _set_payload(
        name="year_timeline_full_sim_quarter_start_64",
        description="Quarter-start heavy full-sim sample with setup, admin, and onboarding clutter.",
        sample_ids=quarter_start[:64],
    )


def build_full_sim_finals_window_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    finals = [
        row["sample_id"]
        for row in samples
        if row.get("week_stage") == "finals_rollover" or row.get("season_tag") == "finals-window"
    ]
    return _set_payload(
        name="year_timeline_full_sim_finals_window_64",
        description="Finals-window sample with review-session clutter, grade release, and heavy wrapper noise.",
        sample_ids=finals[:64],
    )


def build_full_sim_mixed_regression_set(samples: list[dict[str, Any]]) -> dict[str, Any]:
    selected: list[str] = []
    for phase_label in ("WI26", "SP26", "SU26", "FA26"):
        phase_rows = [row for row in samples if row.get("phase_label") == phase_label]
        selected.extend(_take_matching(phase_rows, limit=8, full_sim_layer="core_course"))
        selected.extend(_take_matching(phase_rows, limit=10, background_group="academic_non_target"))
        selected.extend(_take_matching(phase_rows, limit=12, background_group="wrapper_clutter"))
        selected.extend(_take_matching(phase_rows, limit=18, background_group="unrelated_general"))
    return _set_payload(
        name="year_timeline_full_sim_mixed_regression_192",
        description="Full-year mixed regression sample spanning all four phases with target signals, wrappers, academic clutter, and unrelated mail.",
        sample_ids=selected[:192],
    )


def _select(samples: list[dict[str, Any]], **criteria: str) -> list[str]:
    out: list[str] = []
    for row in samples:
        if all(str(row.get(key) or "") == value for key, value in criteria.items()):
            out.append(str(row["sample_id"]))
    return out


def _take_matching(samples: list[dict[str, Any]], *, limit: int, **criteria: str) -> list[str]:
    matches = _select(samples, **criteria)
    return matches[:limit]


def _set_payload(*, name: str, description: str, sample_ids: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "sample_ids_by_bucket": {FULL_SIM_BUCKET: sample_ids},
    }


def _count_by_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get(key) if row.get(key) is not None else "null")] += 1
    return dict(counts)


__all__ = [
    "FULL_SIM_BUCKET",
    "build_full_sim_academic_noise_set",
    "build_full_sim_bucket_manifest",
    "build_full_sim_false_positive_bait_set",
    "build_full_sim_finals_window_set",
    "build_full_sim_mixed_regression_set",
    "build_full_sim_quarter_start_set",
    "build_full_sim_smoke_set",
    "build_full_sim_wrapper_heavy_set",
    "compose_year_timeline_full_sim",
]
