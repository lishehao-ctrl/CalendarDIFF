from __future__ import annotations

from dataclasses import dataclass, field


class LlmParseError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        provider: str,
        parser_version: str = "mainline",
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.provider = provider
        self.parser_version = parser_version
        super().__init__(message)


@dataclass(frozen=True)
class ParserContext:
    source_id: int
    provider: str
    source_kind: str
    request_id: str | None = None


@dataclass(frozen=True)
class ParserOutput:
    records: list[dict] = field(default_factory=list)
    parser_name: str = "unknown_parser"
    parser_version: str = "mainline"
    model_hint: str = "unknown_model"
