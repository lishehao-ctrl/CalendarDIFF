from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import ParserContext
from app.modules.ingestion.llm_parsers.gmail_parser_llm import LlmInvokeCallable, invoke_schema_validated
from app.modules.ingestion.llm_parsers.schemas import GmailPlannerResponse
from app.modules.llm_gateway import LlmInvokeRequest

GMAIL_SHARED_PREFIX_PROMPT = (
    "You are a Gmail course-work/test parser. "
    "Focus only on homework-like course work or test-like assessments. "
    "Homework-like means any required deliverable or submission. "
    "Test-like means quizzes, exams, midterms, finals, or similar assessments. "
    "Ignore lab, discussion, section, grade-only, newsletter, campus admin, marketing, competition, recruiting, memo, "
    "study-note, solutions, meeting, voting, corporate, and other non-course content unless it clearly changes "
    "homework-like work or test-like assessment requirements. "
)


def plan_gmail_segments(
    *,
    db: Session,
    context: ParserContext,
    source_message_id: str | None,
    source_subject: str,
    source_snippet: str | None,
    source_body_text: str | None,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    invoke_json: LlmInvokeCallable,
) -> tuple[GmailPlannerResponse, str | None]:
    invoke_request = LlmInvokeRequest(
        task_name="gmail_message_segment_plan",
        system_prompt=(
            f"{GMAIL_SHARED_PREFIX_PROMPT}"
            "Classify message text into extraction segments. "
            "Only use atomic or directive when there is clear course context, such as a course identifier, "
            "class context, LMS sender, or unmistakable course-specific wording. "
            'Return JSON: {"message_id":string|null,"mode":string,"segment_array":[{"segment_index":number,'
            '"anchor":string|null,"snippet":string|null,"segment_type_hint":"atomic"|"directive"|"unknown"}]}. '
            "Use segment_type_hint=atomic for independent homework-like or test-like change statements. "
            "Use directive when the text is a batch rule or instruction targeting homework-like work or test-like assessments. "
            "Use unknown for anything outside the monitored work/test scope or when relevance is genuinely unclear."
        ),
        user_payload={"stage": "planner"},
        shared_user_payload={
            "message_id": source_message_id,
            "subject": source_subject,
            "snippet": source_snippet,
            "body_text": source_body_text,
            "from_header": source_from_header,
            "thread_id": source_thread_id,
            "internal_date": source_internal_date,
        },
        output_schema_name="GmailPlannerResponse",
        output_schema_json=GmailPlannerResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
        session_cache_mode="enable",
    )
    return invoke_schema_validated(
        db=db,
        context=context,
        invoke_request=invoke_request,
        response_model=GmailPlannerResponse,
        stage_label="gmail_message_segment_plan",
        invoke_json=invoke_json,
    )


__all__ = ["plan_gmail_segments"]
