from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.db.models.runtime import ConnectorResultStatus
from app.db.models.review import EventEntity, EventEntityLifecycle
from app.db.models.shared import User
from app.core.config import get_settings
from app.modules.runtime.connectors.calendar_fetcher import fetch_calendar_delta
from app.modules.runtime.connectors.clients.gmail_client import GmailAPIError
from app.modules.runtime.connectors.gmail_second_filter import GmailSecondFilterDecision
from app.modules.runtime.connectors.gmail_fetcher import (
    _known_course_tokens_for_source,
    fetch_gmail_changes,
    matches_gmail_source_filters,
)
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source
from app.modules.families.family_service import create_course_work_item_family


def _expected_gmail_end_exclusive(timezone_name: str = "America/Los_Angeles") -> str:
    local_today = datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name)).date()
    return (local_today + timedelta(days=1)).strftime("%Y/%m/%d")


def test_gmail_fetcher_missing_access_token_fails_auth(monkeypatch) -> None:
    source = SimpleNamespace(config=None, cursor=None)
    monkeypatch.setattr(
        "app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets",
        lambda _source: {},
    )
    outcome = fetch_gmail_changes(source=source, request_id="req-1")
    assert outcome.status == ConnectorResultStatus.AUTH_FAILED
    assert outcome.error_code == "gmail_missing_access_token"
    assert outcome.parse_payload is None


def test_calendar_fetcher_missing_url_fails_auth(monkeypatch) -> None:
    source = SimpleNamespace(id=100, cursor=None)
    monkeypatch.setattr(
        "app.modules.runtime.connectors.calendar_fetcher.decode_source_secrets",
        lambda _source: {},
    )
    outcome = fetch_calendar_delta(source=source)
    assert outcome.status == ConnectorResultStatus.AUTH_FAILED
    assert outcome.error_code == "calendar_missing_url"
    assert outcome.parse_payload is None


def test_gmail_filter_contract_honors_subject_and_sender() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX", "COURSE"],
        from_header="professor@school.edu",
        subject="Homework deadline reminder",
        snippet="Assignment due Friday",
        body_text="Please note the homework deadline has moved.",
    )
    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={
                "subject_keywords": ["deadline", "exam"],
                "from_contains": "school.edu",
                "label_ids": ["COURSE"],
            },
        )
        is True
    )
    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={"subject_keywords": ["quiz"], "from_contains": "school.edu"},
        )
        is False
    )


def test_gmail_filter_defaults_to_inbox_and_conservative_metadata_gate() -> None:
    inbox_metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="notifications@instructure.com",
        subject="Assignment due date changed",
        snippet="Canvas assignment reminder",
        body_text="The due date has changed.",
        internal_date="2026-02-01T15:00:00+00:00",
    )
    archive_metadata = SimpleNamespace(
        label_ids=["IMPORTANT"],
        from_header="notifications@instructure.com",
        subject="Assignment due date changed",
        snippet="Canvas assignment reminder",
        body_text="The due date has changed.",
        internal_date="2026-02-01T15:00:00+00:00",
    )
    non_course_metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="friend@example.com",
        subject="Weekend brunch",
        snippet="See you there",
        body_text="Not a school message.",
        internal_date="2026-02-01T15:00:00+00:00",
    )
    generic_edu_metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="Office of Student Affairs <vcsacl@ucsd.edu>",
        subject="Time to DANCE, Tritons!",
        snippet="Student life event announcement",
        body_text="Join us for campus programming this weekend.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=inbox_metadata, config={}) is True
    assert matches_gmail_source_filters(metadata=archive_metadata, config={}) is False
    assert matches_gmail_source_filters(metadata=non_course_metadata, config={}) is False
    assert matches_gmail_source_filters(metadata=generic_edu_metadata, config={}) is False


def test_gmail_filter_allows_sender_only_signal_in_inbox() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="announcements@canvas.ucsd.edu",
        subject="Course update",
        snippet="Please review the update",
        body_text="General course notice",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_allows_high_frequency_lms_sender_only_signal_in_inbox() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="no-reply@brightspace.example.edu",
        subject="Course update",
        snippet="Please review the update",
        body_text="General course notice",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_does_not_treat_slack_as_sender_only_strong_signal() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="notifications@slack.com",
        subject="Slack digest",
        snippet="Workspace activity",
        body_text="A teammate mentioned you in a channel.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is False


def test_gmail_filter_allows_keyword_only_signal_in_inbox() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="friend@example.com",
        subject="Homework due tonight",
        snippet="deadline update",
        body_text="Your homework deadline changed",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_allows_deliverable_keyword_for_unknown_sender() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="reminders@example.com",
        subject="Team Deliverable 3 timing note",
        snippet="Deliverable 3 is due Tuesday at 5 PM.",
        body_text="The team deliverable must be submitted by Tuesday at 5 PM.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_allows_checkpoint_keyword_for_unknown_sender() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="updates@example.com",
        subject="Checkpoint 2 timing confirmed",
        snippet="Project checkpoint 2 remains due Sunday evening.",
        body_text="Checkpoint 2 remains due Sunday at 8 PM.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_allows_lab_report_phrase_for_unknown_sender() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="course-bot@example.com",
        subject="Lab Report 2 updated",
        snippet="Lab Report 2 should be turned in Friday.",
        body_text="Lab report 2 should be turned in Friday before midnight.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_excludes_lab_and_discussion_keyword_only_messages() -> None:
    lab_metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="friend@example.com",
        subject="Lab moved to Thursday",
        snippet="lab update",
        body_text="The lab section has a room change.",
        internal_date="2026-02-01T15:00:00+00:00",
    )
    discussion_metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="friend@example.com",
        subject="Discussion section moved",
        snippet="discussion section update",
        body_text="The discussion section moved to a different time.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=lab_metadata, config={}) is False
    assert matches_gmail_source_filters(metadata=discussion_metadata, config={}) is False


def test_gmail_filter_allows_known_course_token_even_without_edu_sender() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="no-reply@gradescope.com",
        subject="CSE 120 HW1 available",
        snippet="Your assignment is now available",
        body_text="CSE120 homework posted",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={},
            known_course_tokens={"cse 120", "cse120"},
        )
        is True
    )


def test_gmail_filter_keeps_lms_wrapper_with_explicit_non_target_phrase_for_secondary_filter() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="notifications@canvas.example.edu",
        subject="Canvas comment for CSE 120",
        snippet="An LMS comment or notification was posted, but no monitored deadline changed.",
        body_text="You are receiving this notification because activity occurred in CSE 120. No monitored deadline changed.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={},
            known_course_tokens={"cse 120", "cse120"},
        )
        is True
    )


def test_gmail_filter_keeps_student_services_bait_for_secondary_filter() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="EASy Requests <services@students.example.edu>",
        subject="Easy Request assignment follow-up",
        snippet="Student services notice. The wording contains assignment even though the message is unrelated to monitored course work.",
        body_text="Student services notice. Please use the student services portal for follow-up.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_secondary_classifier_can_suppress_after_recall_first_prefilter(monkeypatch) -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="CloudStorage Plus <shipping@cloudstorage-plus.example>",
        subject="Project shipment exception notice",
        snippet="Shipping exception notification for your storage subscription",
        body_text="This is a subscription update and package tracking notice. No academic deadline changed.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_MODE", "enforce")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.modules.runtime.connectors.gmail_fetcher.run_gmail_second_filter",
        lambda **kwargs: GmailSecondFilterDecision(
            action="suppress",
            stage="distilbert_shadow",
            reason_code="shipping_subscription_bait",
            confidence=0.999,
        ),
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is False
    get_settings.cache_clear()


def test_gmail_filter_secondary_classifier_shadow_does_not_suppress(monkeypatch) -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="CloudStorage Plus <shipping@cloudstorage-plus.example>",
        subject="Project shipment exception notice",
        snippet="Shipping exception notification for your storage subscription",
        body_text="This is a subscription update and package tracking notice. No academic deadline changed.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_MODE", "shadow")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.modules.runtime.connectors.gmail_fetcher.run_gmail_second_filter",
        lambda **kwargs: GmailSecondFilterDecision(
            action="suppress",
            stage="distilbert_shadow",
            reason_code="shipping_subscription_bait",
            confidence=0.999,
        ),
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True
    get_settings.cache_clear()


def test_gmail_filter_small_diff_batch_bypasses_secondary_classifier(monkeypatch) -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="CloudStorage Plus <shipping@cloudstorage-plus.example>",
        subject="Project shipment exception notice",
        snippet="Shipping exception notification for your storage subscription",
        body_text="This is a subscription update and package tracking notice. No academic deadline changed.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    monkeypatch.setenv("GMAIL_SECONDARY_FILTER_MODE", "enforce")
    get_settings.cache_clear()
    assert matches_gmail_source_filters(
        metadata=metadata,
        config={},
        gmail_diff_message_count=10,
    ) is True
    get_settings.cache_clear()


def test_gmail_filter_keeps_target_signal_even_with_unchanged_footer_text() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="cse120-staff@courses.example.edu",
        subject="[CSE120] Homework 4 due date updated",
        snippet="Homework 4 is now due Thursday, October 15 at 11:59 PM PT.",
        body_text=(
            "Homework 4 is now due Thursday, October 15 at 11:59 PM PT instead of Tuesday. "
            "Grade weights and rubric points are unchanged."
        ),
        internal_date="2026-10-15T12:00:00+00:00",
    )

    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={},
            known_course_tokens={"cse 120", "cse120"},
        )
        is True
    )


def test_gmail_filter_blocks_recruiting_bait_with_explicit_non_target_text() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="Vertex Recruiting <talent@careers.example.com>",
        subject="Internship Application submission update",
        snippet="Recruiting logistics are unrelated to monitored course deadlines.",
        body_text="Recruiting workflow update. Recruiting logistics are unrelated to monitored course deadlines. This mailbox is not monitored.",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is False


def test_gmail_filter_keeps_newsletter_digest_bait_for_secondary_filter() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="Campus Weekly <digest@lists.example.com>",
        subject="Quarter Start digest: assignment, events, and inbox clutter",
        snippet="Digest content bundles many prompts together and should stay non-target.",
        body_text="Quarter Start newsletter. Digest content bundles many prompts together and should stay non-target. Unsubscribe | Manage preferences | View in browser",
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert matches_gmail_source_filters(metadata=metadata, config={}) is True


def test_gmail_filter_keeps_academic_non_target_with_course_token_for_secondary_filter() -> None:
    metadata = SimpleNamespace(
        label_ids=["INBOX"],
        from_header="Registrar Updates <noreply@campus.example.edu>",
        subject="[MATH18] section waitlist admin and submission note",
        snippet="Discussion waitlist handling changed and the graded submission schedule is unchanged.",
        body_text=(
            "Course context: MATH18. Discussion waitlist handling changed and the graded submission schedule is unchanged. "
            "This email is academic context only and should not create a monitored event in the canonical timeline."
        ),
        internal_date="2026-02-01T15:00:00+00:00",
    )

    assert (
        matches_gmail_source_filters(
            metadata=metadata,
            config={},
            known_course_tokens={"math 18", "math18"},
        )
        is True
    )


def test_gmail_fetcher_bootstraps_monitoring_window_messages(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "label_id": "COURSE",
                "monitor_since": "2026-01-05",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == f"after:2026/01/05 before:{_expected_gmail_end_exclusive()}"
            assert label_ids == ["COURSE"]
            return ["m1", "m2"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            assert access_token == "token"
            internal_date = {
                "m1": "2026-02-01T15:00:00+00:00",
                "m2": "2025-12-01T15:00:00+00:00",
            }[message_id]
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet=f"snippet-{message_id}",
                body_text=f"body-{message_id}",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date=internal_date,
                label_ids=["COURSE"],
            )

    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)

    outcome = fetch_gmail_changes(source=source, request_id="req-bootstrap")

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.cursor_patch == {"history_id": "200"}
    assert outcome.parse_payload is not None
    assert outcome.parse_payload["kind"] == "gmail"
    assert [row["message_id"] for row in outcome.parse_payload["messages"]] == ["m1"]


def test_gmail_fetcher_bootstrap_defaults_to_inbox_when_label_missing(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "monitor_since": "2026-01-05",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
        user_id=1,
    )

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == f"after:2026/01/05 before:{_expected_gmail_end_exclusive()}"
            assert label_ids == ["INBOX"]
            return ["m1"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            assert access_token == "token"
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet="Assignment due tomorrow",
                body_text="The homework due date changed.",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date="2026-02-01T15:00:00+00:00",
                label_ids=["INBOX"],
            )

    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher._known_course_tokens_for_source", lambda _source: set())

    outcome = fetch_gmail_changes(source=source, request_id="req-bootstrap-default-inbox")

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert [row["message_id"] for row in outcome.parse_payload["messages"]] == ["m1"]


def test_gmail_fetcher_skips_missing_gmail_message_metadata_404(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "label_id": "INBOX",
                "monitor_since": "2026-01-05",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == f"after:2026/01/05 before:{_expected_gmail_end_exclusive()}"
            assert label_ids == ["INBOX"]
            return ["m1", "m404", "m2"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            assert access_token == "token"
            if message_id == "m404":
                raise GmailAPIError(status_code=404, message="Requested entity was not found.")
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet="Assignment due tomorrow",
                body_text="The homework due date changed.",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date="2026-02-01T15:00:00+00:00",
                label_ids=["INBOX"],
            )

    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher._known_course_tokens_for_source", lambda _source: set())

    outcome = fetch_gmail_changes(source=source, request_id="req-bootstrap-skip-404")

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert [row["message_id"] for row in outcome.parse_payload["messages"]] == ["m1", "m2"]


def test_gmail_fetcher_emits_bootstrap_progress(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "label_id": "COURSE",
                "monitor_since": "2026-01-05",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )
    progress_events: list[dict] = []

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == f"after:2026/01/05 before:{_expected_gmail_end_exclusive()}"
            assert label_ids == ["COURSE"]
            return ["m1", "m2"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet=f"snippet-{message_id}",
                body_text=f"body-{message_id}",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date="2026-02-01T15:00:00+00:00",
                label_ids=["COURSE"],
            )

    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)

    outcome = fetch_gmail_changes(
        source=source,
        request_id="req-bootstrap-progress",
        emit_progress=lambda payload: progress_events.append(payload),
    )

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert len(progress_events) >= 2
    assert progress_events[0]["phase"] == "gmail_bootstrap_fetch"
    assert progress_events[0]["current"] == 0
    assert progress_events[0]["total"] == 2
    assert progress_events[-1]["current"] == 2
    assert progress_events[-1]["total"] == 2


def test_gmail_fetcher_emits_tail_progress_for_small_remaining_window(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "label_id": "COURSE",
                "monitor_since": "2026-01-05",
            }
        ),
        cursor=SimpleNamespace(cursor_json={"history_id": "150"}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )
    progress_events: list[dict] = []

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_history(self, *, access_token: str, start_history_id: str):
            assert access_token == "token"
            assert start_history_id == "150"
            return SimpleNamespace(message_ids=[f"m{i}" for i in range(1, 13)], history_id="200")

        def get_message_metadata(self, *, access_token: str, message_id: str):
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet=f"snippet-{message_id}",
                body_text=f"body-{message_id}",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date="2026-02-01T15:00:00+00:00",
                label_ids=["COURSE"],
            )

    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)

    outcome = fetch_gmail_changes(
        source=source,
        request_id="req-history-progress",
        emit_progress=lambda payload: progress_events.append(payload),
    )

    assert outcome.status == ConnectorResultStatus.CHANGED
    current_values = [row["current"] for row in progress_events if row["phase"] == "gmail_history_fetch"]
    assert current_values[0] == 0
    assert 10 in current_values
    assert 11 in current_values
    assert 12 in current_values


def test_known_course_tokens_for_source_include_recent_family_mappings(db_session) -> None:
    user = User(
        email=None,
        notify_email="tokens@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Gmail Inbox",
            config={"label_id": "INBOX", "monitor_since": "2026-01-05"},
            secrets={},
        ),
    )

    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        canonical_label="Homework",
        raw_types=["hw"],
    )
    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="MATH",
        course_number=20,
        course_suffix="C",
        course_quarter="WI",
        course_year2=26,
        canonical_label="Quiz",
        raw_types=["quiz"],
    )
    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="CHEM",
        course_number=6,
        course_suffix="A",
        course_quarter="FA",
        course_year2=25,
        canonical_label="Homework",
        raw_types=["hw"],
    )

    tokens = _known_course_tokens_for_source(source)

    assert "cse 100" in tokens
    assert "cse100" in tokens
    assert "math 20c" in tokens
    assert "math20c" in tokens
    assert "chem 6a" in tokens
    assert "chem6a" in tokens


def test_known_course_tokens_for_source_uses_recent_entities_to_scope_mappings(db_session) -> None:
    user = User(
        email=None,
        notify_email="tokens-entities@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Gmail Inbox",
            config={"label_id": "INBOX", "monitor_since": "2026-01-05"},
            secrets={},
        ),
    )

    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="CSE",
        course_number=120,
        canonical_label="Homework",
        raw_types=["hw"],
    )
    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="HIST",
        course_number=10,
        canonical_label="Discussion",
        raw_types=["discussion"],
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="entity-cse120",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=120,
            raw_type="Homework",
            event_name="HW1",
            due_date=date(2026, 2, 10),
            time_precision="date_only",
        )
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="entity-hist10-old",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="HIST",
            course_number=10,
            raw_type="Discussion",
            event_name="Week 1",
            due_date=date(2025, 11, 10),
            time_precision="date_only",
        )
    )
    db_session.commit()

    tokens = _known_course_tokens_for_source(source)

    assert "cse 120" in tokens
    assert "cse120" in tokens
    assert "hist 10" not in tokens
    assert "hist10" not in tokens


def test_gmail_fetcher_bootstrap_uses_monitoring_window_course_mapping_tokens(monkeypatch, db_session) -> None:
    user = User(
        email=None,
        notify_email="tokens-bootstrap@example.com",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Gmail Inbox",
            config={"label_id": "INBOX", "monitor_since": "2026-01-05"},
            secrets={},
        ),
    )
    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        canonical_label="Homework",
        raw_types=["hw"],
    )
    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="CHEM",
        course_number=6,
        course_suffix="A",
        course_quarter="FA",
        course_year2=25,
        canonical_label="Homework",
        raw_types=["hw"],
    )

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == f"after:2026/01/05 before:{_expected_gmail_end_exclusive()}"
            assert label_ids == ["INBOX"]
            return ["m1", "m2"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            body_text = {
                "m1": "CSE100 announcement and logistics update",
                "m2": "CHEM6A announcement and logistics update",
            }[message_id]
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet="general update",
                body_text=body_text,
                from_header="student-forum@example.com",
                subject="Course note",
                internal_date="2026-02-01T15:00:00+00:00",
                label_ids=["INBOX"],
            )

    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.runtime.connectors.gmail_fetcher.GmailClient", _FakeGmailClient)

    outcome = fetch_gmail_changes(source=source, request_id="req-bootstrap-course-token")

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert [row["message_id"] for row in outcome.parse_payload["messages"]] == ["m1", "m2"]


def test_calendar_fetcher_filters_changed_components_before_monitoring_window(monkeypatch) -> None:
    source = SimpleNamespace(
        id=100,
        config=SimpleNamespace(
            config_json={
                "monitor_since": "2026-01-05",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )
    monkeypatch.setattr("app.modules.runtime.connectors.calendar_fetcher.decode_source_secrets", lambda _source: {"url": "https://example.com/calendar.ics"})

    class _FakeFetched:
        not_modified = False
        etag = "etag-1"
        last_modified = "Mon, 01 Jan 2026 00:00:00 GMT"

        def __init__(self, content: bytes):
            self.content = content

    class _FakeIcsClient:
        def fetch(self, url: str, source_id: int, if_none_match=None, if_modified_since=None):
            assert url == "https://example.com/calendar.ics"
            assert source_id == 100
            del if_none_match, if_modified_since
            content = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-in
DTSTART:20260201T180000Z
DTEND:20260201T190000Z
SUMMARY:In monitoring window
END:VEVENT
BEGIN:VEVENT
UID:evt-old
DTSTART:20241201T180000Z
DTEND:20241201T190000Z
SUMMARY:Before monitoring window
END:VEVENT
END:VCALENDAR
"""
            return _FakeFetched(content)

    monkeypatch.setattr("app.modules.runtime.connectors.calendar_fetcher.ICSClient", _FakeIcsClient)

    outcome = fetch_calendar_delta(source=source)

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert outcome.parse_payload["kind"] == "calendar_delta"
    changed = outcome.parse_payload["changed_components"]
    assert len(changed) == 1
    assert changed[0]["external_event_id"] == "evt-in"
