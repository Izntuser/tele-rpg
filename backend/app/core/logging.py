"""Shared logging setup for every process (api, scheduler, dev bot).

Railway labels each stderr line "error", so INFO must go to stdout. In prod each record is one
JSON object per line (Railway reads its ``level``); elsewhere a human-readable format, with
WARNING and above on stderr. Safe to call more than once and never removes foreign handlers
(pytest's caplog).
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import TextIO

from app.core.config import Settings, get_settings

_MARK = "_tele_rpg_handler"
_QUIET = ("apscheduler", "apscheduler.executors.default", "apscheduler.scheduler")
_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")
_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


_LEVELS = {"warning": "warn", "critical": "error"}  # Railway: debug/info/warn/error
_WEBHOOK_RE = re.compile(r"/tg/webhook/[^?\s\"']*")
_BOT_TOKEN_RE = re.compile(r"\bbot\d{3,}:[A-Za-z0-9_-]{10,}")


def redact(text: str) -> str:
    """Hide the webhook path secret and Telegram bot tokens (api.telegram.org/bot<TOKEN>/...)."""
    return _BOT_TOKEN_RE.sub("bot[redacted]", _WEBHOOK_RE.sub("/tg/webhook/[redacted]", text))


class RedactFilter(logging.Filter):
    """Scrub secrets from a record's msg and args. Attach to a logger (handlers get cleared)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in args)
        elif isinstance(args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in args.items()}
        return True


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname.lower()
        payload: dict[str, str] = {
            "level": _LEVELS.get(level, level),
            "message": redact(record.getMessage()),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        elif record.exc_text:
            payload["exception"] = redact(record.exc_text)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _MaxLevel(logging.Filter):
    """Pass records strictly below ``level``."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self._level


def _handler(stream: TextIO, formatter: logging.Formatter) -> logging.StreamHandler[TextIO]:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    setattr(handler, _MARK, True)
    return handler


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(old)
    root.setLevel(logging.INFO)
    if settings.app_env == "prod":
        root.addHandler(_handler(sys.stdout, JsonFormatter()))
    else:
        fmt = _RedactingFormatter(_TEXT_FORMAT)
        out = _handler(sys.stdout, fmt)
        out.addFilter(_MaxLevel(logging.WARNING))
        err = _handler(sys.stderr, fmt)
        err.setLevel(logging.WARNING)
        root.addHandler(out)
        root.addHandler(err)
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn installs its own stderr handlers; route its loggers through the root's instead.
    for name in _UVICORN:
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactFilter) for f in access.filters):
        access.addFilter(RedactFilter())
