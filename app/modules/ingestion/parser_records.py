from __future__ import annotations

from app.modules.ingestion.llm_parsers import ParserOutput


def attach_parser_metadata(*, records: list[dict], parser_output: ParserOutput) -> list[dict]:
    parser_meta = {
        "name": parser_output.parser_name,
        "version": parser_output.parser_version,
        "model": parser_output.model_hint,
    }
    enriched: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_type = record.get("record_type")
        payload = record.get("payload")
        if not isinstance(record_type, str) or not isinstance(payload, dict):
            continue
        payload_json = dict(payload)
        payload_json["_parser"] = parser_meta
        enriched.append(
            {
                "record_type": record_type,
                "payload": payload_json,
            }
        )
    return enriched
