import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SECRETS = re.compile(
    r"(?:sk-[A-Za-z0-9_-]+|monid_live_[A-Za-z0-9_-]+|pio_(?:at|rt)_[A-Za-z0-9_-]+"
    r"|(?<=Bearer )[A-Za-z0-9._~+/=-]{12,})"
)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRETS.sub("[redacted]", value)
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    return {key: _redact(item) for key, item in event_dict.items()}


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SECRETS.sub("[redacted]", record.msg)
        if record.args:
            record.args = tuple(_redact(item) for item in record.args) if isinstance(
                record.args, tuple
            ) else record.args
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, _RedactingFilter) for item in handler.filters):
            handler.addFilter(_RedactingFilter())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_secrets,
            structlog.processors.JSONRenderer(),
        ]
    )
