from __future__ import annotations

from collections import Counter, defaultdict

from tools.datasets.year_timeline_background_stream import (
    BACKGROUND_PER_BATCH,
    build_background_email_samples,
    build_year_timeline_background_stream,
)
from tools.datasets.year_timeline_full_sim import compose_year_timeline_full_sim
from tools.datasets.year_timeline_scenarios import build_year_timeline_manifest


def test_year_timeline_background_stream_is_deterministic_and_dense() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    stream_a = build_year_timeline_background_stream(manifest=manifest)
    stream_b = build_year_timeline_background_stream(manifest=manifest)

    assert stream_a.to_dict() == stream_b.to_dict()
    assert len(stream_a.batches) == 4 * 12
    assert stream_a.total_messages == 4 * 12 * BACKGROUND_PER_BATCH

    categories = Counter()
    groups = Counter()
    senders = Counter()
    bait_count = 0
    for batch in stream_a.batches:
        assert len(batch.messages) == BACKGROUND_PER_BATCH
        for message in batch.messages:
            categories[message.background_category] += 1
            groups[message.background_group] += 1
            senders[message.sender_role] += 1
            if message.is_false_positive_bait:
                bait_count += 1

    assert set(categories) == {
        "personal_finance",
        "commerce",
        "package_subscription",
        "account_security",
        "housing",
        "campus_admin",
        "student_services",
        "clubs_and_events",
        "newsletter",
        "jobs_and_careers",
        "calendar_wrapper",
        "academic_non_target",
        "lms_wrapper_noise",
    }
    assert groups["academic_non_target"] == 4 * 12 * 36
    assert groups["wrapper_clutter"] == 4 * 12 * 54
    assert groups["unrelated_general"] == 4 * 12 * 114
    assert bait_count > stream_a.total_messages * 0.8
    assert senders["campus_office"] > 0
    assert senders["housing_sender"] > 0
    assert senders["student_services_sender"] > 0
    assert senders["recruiter"] > 0
    assert senders["lms_wrapper_sender"] > 0


def test_year_timeline_background_stream_shifts_with_seasonality() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    stream = build_year_timeline_background_stream(manifest=manifest)

    by_phase_and_stage: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    season_tags = Counter()
    for batch in stream.batches:
        for message in batch.messages:
            by_phase_and_stage[(batch.phase_label, batch.week_stage)][message.background_category] += 1
            season_tags[message.season_tag] += 1

    assert by_phase_and_stage[("WI26", "setup_release")]["campus_admin"] > by_phase_and_stage[("WI26", "setup_release")]["jobs_and_careers"]
    assert by_phase_and_stage[("SP26", "project_push")]["jobs_and_careers"] > by_phase_and_stage[("WI26", "project_push")]["jobs_and_careers"]
    assert by_phase_and_stage[("FA26", "finals_rollover")]["commerce"] > by_phase_and_stage[("FA26", "setup_release")]["commerce"]
    assert by_phase_and_stage[("SU26", "project_push")]["clubs_and_events"] > 0
    assert season_tags["internship-season"] > 0
    assert season_tags["holiday-commerce"] > 0
    assert season_tags["finals-window"] > 0


def test_year_timeline_full_sim_composition_keeps_core_minority_and_truth() -> None:
    manifest = build_year_timeline_manifest().to_dict()
    core_samples = []
    for phase in manifest["plans"]:
        for batch in phase["batches"]:
            core_samples.extend(
                {
                    "sample_id": row["message_id"],
                    "message_id": row["message_id"],
                    "thread_id": row["thread_id"],
                    "subject": row["subject"],
                    "from_header": row["from_header"],
                    "body_text": row["body_text"],
                    "internal_date": row["internal_date"],
                    "label_ids": row["label_ids"],
                    "collection_bucket": "year_timeline_gmail",
                    "expected_mode": "directive" if row["message_kind"] == "directive" else "atomic" if row["message_kind"] in {"atomic_new", "atomic_change"} else "unknown",
                    "expected_record_type": "gmail.directive.extracted" if row["message_kind"] == "directive" else "gmail.message.extracted" if row["message_kind"] in {"atomic_new", "atomic_change"} else None,
                }
                for row in batch["gmail_messages"]
            )
    background = build_background_email_samples(manifest=manifest)
    mixed = compose_year_timeline_full_sim(core_samples=core_samples, background_samples=background)

    assert len(mixed) == len(core_samples) + len(background)
    assert sum(1 for row in mixed if row["full_sim_layer"] == "core_course") == len(core_samples)
    assert sum(1 for row in mixed if row["full_sim_layer"] == "background_noise") == len(background)
    assert len(core_samples) / len(mixed) < 0.06

    core_by_id = {row["sample_id"]: row for row in core_samples}
    mixed_core = {row["sample_id"]: row for row in mixed if row["full_sim_layer"] == "core_course"}
    assert mixed_core.keys() == core_by_id.keys()
    for sample_id, row in mixed_core.items():
        assert row["expected_mode"] == core_by_id[sample_id]["expected_mode"]
        assert row["expected_record_type"] == core_by_id[sample_id]["expected_record_type"]
