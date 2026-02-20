from __future__ import annotations

import logging
import re


_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_log_message(record.msg)
        if record.args:
            sanitized_args = []
            for arg in record.args if isinstance(record.args, tuple) else (record.args,):
                if isinstance(arg, str):
                    sanitized_args.append(sanitize_log_message(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        return True


def sanitize_log_message(message: str) -> str:
    return _URL_PATTERN.sub("[REDACTED_URL]", message)


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
