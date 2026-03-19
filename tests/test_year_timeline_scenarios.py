from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from tools.datasets.year_timeline_scenarios import build_year_timeline_manifest


def test_year_timeline_manifest_shape_and_volume() -> None:
    manifest = build_year_timeline_manifest()
    assert manifest.version == "year-timeline-current"
    assert manifest.semesters == 4
    assert manifest.batches_per_semester == 12
    assert manifest.batch_size == 12
    assert len(manifest.plans) == 4

    total_ics = 0
    total_gmail = 0
    for phase in manifest.plans:
        assert len(phase.courses) == 3
        assert len(phase.batches) == 12
        for batch in phase.batches:
            assert len(batch.ics_events) == 12
            assert len(batch.gmail_messages) == 12
            total_ics += len(batch.ics_events)
            total_gmail += len(batch.gmail_messages)

    assert total_ics == 4 * 12 * 12
    assert total_gmail == 4 * 12 * 12


def test_year_timeline_manifest_contains_continuity_message_mix_and_roles() -> None:
    manifest = build_year_timeline_manifest()
    continuity_counts: Counter[str] = Counter()
    message_kinds: Counter[str] = Counter()
    actor_roles: Counter[str] = Counter()
    per_batch: list[Counter[str]] = []

    for phase in manifest.plans:
        for batch in phase.batches:
            kinds = Counter()
            for event in batch.ics_events:
                continuity_counts[event.continuity_key] += 1
            for message in batch.gmail_messages:
                message_kinds[message.message_kind] += 1
                actor_roles[message.actor_role] += 1
                kinds[message.message_kind] += 1
            per_batch.append(kinds)

    repeated = [key for key, count in continuity_counts.items() if count >= 3]
    assert len(repeated) >= 12
    for kinds in per_batch:
        assert kinds["atomic_new"] == 3
        assert kinds["atomic_change"] == 3
        assert kinds["directive"] == 2
        assert kinds["reminder_noise"] == 2
        assert kinds["lab_noise"] == 1
        assert kinds["admin_noise"] == 1
    assert message_kinds["directive"] == 4 * 12 * 2
    assert actor_roles["professor"] > 0
    assert actor_roles["ta"] > 0
    assert actor_roles["course_staff_alias"] > 0
    assert actor_roles["canvas_wrapper"] > 0
    assert actor_roles["lab_coordinator"] > 0
    assert actor_roles["department_admin"] > 0


def test_year_timeline_manifest_reuses_course_stems_across_phases() -> None:
    manifest = build_year_timeline_manifest()
    by_course: dict[str, set[int]] = defaultdict(set)
    for phase in manifest.plans:
        for course in phase.courses:
            by_course[course].add(phase.semester)

    assert by_course["CSE120"] == {1, 2, 4}
    assert by_course["CSE151A"] == {1, 2, 3}
    assert by_course["DSC10"] == {3, 4}


def test_year_timeline_manifest_contains_expanded_hard_case_tags() -> None:
    manifest = build_year_timeline_manifest()
    tags = Counter()
    for phase in manifest.plans:
        for batch in phase.batches:
            for message in batch.gmail_messages:
                for tag in message.hard_case_tags:
                    tags[tag] += 1
            for event in batch.ics_events:
                for tag in event.hard_case_tags:
                    tags[tag] += 1

    assert tags["single_item_all_sections"] > 0
    assert tags["future_matching_directive"] > 0
    assert tags["ordinal_range"] > 0
    assert tags["ordinal_list"] > 0
    assert tags["alias_hw"] > 0
    assert tags["suffix_sensitive"] > 0
    assert tags["relative_time_phrase"] > 0
    assert tags["absolute_human_phrase"] > 0
    assert tags["ta_pre_notice_then_professor_confirm"] > 0
    assert tags["canvas_wrapper_with_signal_buried"] > 0
    assert tags["calendar_only_due_time_shift"] > 0
    assert tags["email_only_pre_announcement"] > 0
    assert tags["same_item_multi_alias_same_week"] > 0
    assert tags["role_authority_conflict"] > 0
    assert tags["quarter_rollover_admin_noise"] > 0


def test_year_timeline_manifest_directives_and_metadata_are_deterministic() -> None:
    manifest = build_year_timeline_manifest()
    course_profiles: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    message_modes = Counter()
    event_modes = Counter()
    event_kinds = Counter()
    average_leads: dict[str, list[float]] = defaultdict(list)

    for phase in manifest.plans:
        for batch in phase.batches:
            batch_start = datetime.fromisoformat(batch.start_iso)
            for message in batch.gmail_messages:
                course_profiles[message.course.label].add((message.course_archetype, message.teaching_style, message.channel_behavior))
                message_modes[message.channel_timing_mode] += 1
                if message.message_kind == "directive" and message.directive_scope_mode == "ordinal_list":
                    assert len(message.selector_ordinals) >= 2
                    assert len(set(message.selector_ordinals)) == len(message.selector_ordinals)
                if message.message_kind == "directive" and message.directive_scope_mode == "ordinal_range":
                    assert len(message.selector_ordinals) >= 3
                    assert message.selector_ordinals == sorted(message.selector_ordinals)
            for event in batch.ics_events:
                event_modes[event.channel_timing_mode] += 1
                event_kinds[event.ics_change_kind] += 1
                average_leads[phase.phase_label].append((datetime.fromisoformat(event.due_iso) - batch_start).total_seconds() / 86400)

    for values in course_profiles.values():
        assert len(values) == 1
    assert message_modes["canvas_plus_1_batch"] > 0
    assert message_modes["email_plus_1_batch"] > 0
    assert message_modes["email_first"] > 0
    assert event_modes["calendar_only"] > 0
    assert event_kinds["due_time_shift"] > 0
    assert event_kinds["title_alias_change"] > 0
    assert event_kinds["exam_schedule_change"] > 0
    assert sum(average_leads["SU26"]) / len(average_leads["SU26"]) < sum(average_leads["WI26"]) / len(average_leads["WI26"])
