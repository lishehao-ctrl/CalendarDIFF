from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import ParserContext
from app.modules.ingestion.llm_parsers.gmail_parser_llm import LlmInvokeCallable, invoke_schema_validated
from app.modules.ingestion.llm_parsers.schemas import GmailPlannerResponse
from app.modules.llm_gateway import LlmInvokeRequest


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
            "You are pass-1 planner for Gmail deadline parsing. "
            "Classify message text into extraction segments. "
            'Return JSON: {"message_id":string|null,"mode":string,"segment_array":[{"segment_index":number,'
            '"anchor":string|null,"snippet":string|null,"segment_type_hint":"atomic"|"directive"|"unknown"}]}. '
            "Use segment_type_hint=atomic for independent deadline-change statements. "
            "Use directive when the text is instruction-like/meta without direct event extraction. "
            "Use unknown when classification is uncertain."
        ),
        user_payload={
            "source_id": context.source_id,
            "provider": context.provider,
            "source_kind": context.source_kind,
            "message": {
                "message_id": source_message_id,
                "subject": source_subject,
                "snippet": source_snippet,
                "body_text": source_body_text,
                "from_header": source_from_header,
                "thread_id": source_thread_id,
                "internal_date": source_internal_date,
            },
        },
        output_schema_name="GmailPlannerResponse",
        output_schema_json=GmailPlannerResponse.model_json_schema(),
        source_id=context.source_id,
        source_provider=context.provider,
        request_id=context.request_id,
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
