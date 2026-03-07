from __future__ import annotations

from tools.datasets.semester_demo_scenarios import build_scenario_manifest


def test_semester_demo_manifest_shape_and_volume() -> None:
    manifest = build_scenario_manifest(
        semesters=3,
        batches_per_semester=10,
        batch_size=10,
        seed=20260305,
    )
    assert manifest.version == "semester-demo-current"
    assert manifest.semesters == 3
    assert manifest.batches_per_semester == 10
    assert manifest.batch_size == 10
    assert len(manifest.plans) == 3

    for semester_plan in manifest.plans:
        assert len(semester_plan.courses) >= 2
        assert len(semester_plan.batches) == 10
        ics_total = 0
        gmail_total = 0
        for batch in semester_plan.batches:
            assert len(batch.ics_events) == 10
            assert len(batch.gmail_messages) == 10
            ics_total += len(batch.ics_events)
            gmail_total += len(batch.gmail_messages)
        assert ics_total == 100
        assert gmail_total == 100


def test_semester_demo_manifest_contains_suffix_assertion_cases() -> None:
    manifest = build_scenario_manifest(seed=20260305)
    semester1_batch1 = manifest.plans[0].batches[0]
    expected = {
        "suffix_required_missing",
        "suffix_mismatch",
        "auto_link",
    }
    observed = {row.expected_link_outcome for row in semester1_batch1.gmail_messages}
    assert expected.issubset(observed)


def test_semester_demo_manifest_models_gmail_inbox_fields() -> None:
    manifest = build_scenario_manifest(seed=20260305)
    message = manifest.plans[0].batches[0].gmail_messages[0]
    assert message.thread_id.startswith("thread-")
    assert message.from_header.endswith("@example.edu>")
    assert "INBOX" in message.label_ids
    assert isinstance(message.history_batch, int)
    assert isinstance(message.history_global_batch, int)
    assert message.internal_date == message.due_iso
