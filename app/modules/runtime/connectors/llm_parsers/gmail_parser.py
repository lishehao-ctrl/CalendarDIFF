from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.runtime.connectors.llm_parsers.contracts import ParserContext, ParserOutput
from app.modules.runtime.connectors.llm_parsers.semantic_orchestrator import run_semantic_parse_orchestrator


def parse_gmail_payload(*, db: Session, payload: dict, context: ParserContext) -> ParserOutput:
    return run_semantic_parse_orchestrator(
        db=db,
        source_material=payload,
        context=context,
    )


__all__ = ["parse_gmail_payload"]
