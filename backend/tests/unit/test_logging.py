import io
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.core.logging import JsonFormatter, configure_logging, redact
from app.jobs.runner import JobSpec, Runner

_NAMES = ["apscheduler", "apscheduler.executors.default", "apscheduler.scheduler", "t.log"]
_SAVED = ["uvicorn", "uvicorn.error", "uvicorn.access", *_NAMES[:3]]


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    levels = {n: logging.getLogger(n).level for n in _NAMES}
    saved = {
        n: (
            list(logging.getLogger(n).handlers),
            logging.getLogger(n).propagate,
            logging.getLogger(n).level,
            list(logging.getLogger(n).filters),
        )
        for n in _SAVED
    }
    yield
    for n, (hs, prop, lv, fs) in saved.items():
        lg = logging.getLogger(n)
        lg.handlers[:] = hs
        lg.propagate = prop
        lg.setLevel(lv)
        lg.filters[:] = fs
    root.handlers[:] = handlers
    root.setLevel(level)
    for n, lv in levels.items():
        logging.getLogger(n).setLevel(lv)


def _record(level: int, msg: str, exc_info: Any = None) -> logging.LogRecord:
    return logging.LogRecord("some.logger", level, __file__, 1, msg, None, exc_info)


def test_json_formatter_maps_levels_on_one_line() -> None:
    for level, name in [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
        (logging.ERROR, "error"),
        (logging.CRITICAL, "error"),
    ]:
        out = JsonFormatter().format(_record(level, "hello\nworld"))
        assert "\n" not in out
        data = json.loads(out)
        assert data["level"] == name
        assert data["message"] == "hello\nworld"
        assert data["logger"] == "some.logger"
        assert data["time"].endswith("+00:00")
        assert "exception" not in data


def test_json_formatter_renders_exception_field() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        out = JsonFormatter().format(_record(logging.ERROR, "failed", sys.exc_info()))
    assert "\n" not in out
    assert "ValueError: boom" in json.loads(out)["exception"]


def test_prod_logs_json_to_stdout_only(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app_env="test").model_copy(update={"app_env": "prod"}))
    log = logging.getLogger("t.log")
    log.info("hi")
    log.error("bad")
    cap = capsys.readouterr()
    assert cap.err == ""
    lines = [json.loads(x) for x in cap.out.splitlines()]
    assert [(x["level"], x["message"]) for x in lines] == [("info", "hi"), ("error", "bad")]


def test_dev_splits_stdout_and_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app_env="development"))
    log = logging.getLogger("t.log")
    log.info("fine")
    log.warning("careful")
    cap = capsys.readouterr()
    assert "fine" in cap.out and "careful" not in cap.out
    assert "careful" in cap.err and "fine" not in cap.err


def test_configure_is_idempotent_and_keeps_foreign_handlers() -> None:
    foreign = logging.StreamHandler(io.StringIO())
    logging.getLogger().addHandler(foreign)
    configure_logging(Settings(app_env="development"))
    before = len(logging.getLogger().handlers)
    configure_logging(Settings(app_env="development"))
    assert len(logging.getLogger().handlers) == before
    assert foreign in logging.getLogger().handlers


def test_apscheduler_is_quiet_and_uvicorn_uses_root() -> None:
    configure_logging(Settings(app_env="development"))
    for name in ("apscheduler", "apscheduler.executors.default", "apscheduler.scheduler"):
        assert logging.getLogger(name).level == logging.WARNING
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate


async def test_failing_job_logs_error_with_job_name(caplog: pytest.LogCaptureFixture) -> None:
    @asynccontextmanager
    async def session() -> Any:
        yield MagicMock()

    async def broken(_s: Any) -> None:
        raise RuntimeError("nope")

    runner = Runner(MagicMock(), cast(Any, session), {}, max_concurrent_jobs=1)
    with caplog.at_level(logging.ERROR):
        await runner._run_job("my_job", JobSpec(broken, 1))
    rec = next(r for r in caplog.records if r.levelno == logging.ERROR)
    assert "my_job" in rec.getMessage()
    assert rec.exc_info is not None


def _access(path: str) -> None:
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "POST", path, "1.1", 200
    )


@pytest.mark.parametrize("env", ["prod", "development"])
def test_access_log_redacts_webhook_secret(env: str, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(app_env="test").model_copy(update={"app_env": env}))
    configure_logging(Settings(app_env="test").model_copy(update={"app_env": env}))
    assert len([f for f in logging.getLogger("uvicorn.access").filters]) == 1
    _access("/tg/webhook/SUPERSECRET?x=1")
    cap = capsys.readouterr()
    assert "SUPERSECRET" not in cap.out + cap.err
    assert "[redacted]" in cap.out
    if env == "prod":
        assert json.loads(cap.out)["message"].count("/tg/webhook/[redacted]") == 1


def test_uvicorn_log_json_applies_filter(capsys: pytest.CaptureFixture[str]) -> None:
    import logging.config
    from pathlib import Path

    cfg = json.loads((Path(__file__).parents[2] / "uvicorn_log.json").read_text())
    logging.config.dictConfig(cfg)
    _access("/tg/webhook/SUPERSECRET")
    out = capsys.readouterr().out
    assert "SUPERSECRET" not in out and "[redacted]" in out


def test_bot_token_is_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    url = "https://api.telegram.org/bot123456789:AAE-abcdefghijklmnop_QRS/sendMessage"
    assert "AAE" not in redact(url) and "bot[redacted]/sendMessage" in redact(url)
    configure_logging(Settings(app_env="test").model_copy(update={"app_env": "prod"}))
    try:
        raise RuntimeError(url)
    except RuntimeError:
        logging.getLogger("t.log").exception("POST %s", url)
    out = capsys.readouterr().out
    assert "AAE-abcdef" not in out and "bot[redacted]" in out
