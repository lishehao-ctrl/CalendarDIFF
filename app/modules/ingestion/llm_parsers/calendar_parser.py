from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.ingestion.llm_parsers.contracts import ParserContext, ParserOutput
from app.modules.ingestion.llm_parsers.semantic_orchestrator import run_semantic_parse_orchestrator


def parse_calendar_content(*, db: Session, content: bytes, context: ParserContext) -> ParserOutput:
    return run_semantic_parse_orchestrator(
        db=db,
        source_material=content,
        context=context,
    )


__all__ = ["parse_calendar_content"]
