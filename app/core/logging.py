from __future__ import annotations

import logging


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_log_message(record.msg)
        if record.args:
            sanitized_args: list[object] = []
            for arg in record.args if isinstance(record.args, tuple) else (record.args,):
                if isinstance(arg, str):
                    sanitized_args.append(sanitize_log_message(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        return True


def sanitize_log_message(message: str) -> str:
    return _redact_http_urls(message)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    redaction_filter = SecretRedactionFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(redaction_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redaction_filter)


def _redact_http_urls(message: str) -> str:
    out: list[str] = []
    idx = 0
    lower = message.lower()
    while idx < len(message):
        if lower.startswith("http://", idx) or lower.startswith("https://", idx):
            end = idx
            while end < len(message) and not message[end].isspace():
                end += 1
            out.append("[REDACTED_URL]")
            idx = end
            continue
        out.append(message[idx])
        idx += 1
    return "".join(out)
