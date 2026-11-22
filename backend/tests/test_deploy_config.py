import json
import shlex
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]


# Vendored copy of https://railway.com/railway.schema.json (redirects to backboard.railway.app),
# fetched 2026-11-22. Refresh it by re-downloading when Railway changes the schema.
SCHEMA = json.loads((Path(__file__).parent / "fixtures" / "railway.schema.json").read_text())


def load(name: str) -> dict[str, Any]:
    data = json.loads((ROOT / "railway" / f"{name}.json").read_text())
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("name", ["api", "scheduler"])
def test_railway_config_matches_the_official_schema(name: str) -> None:
    jsonschema.validate(load(name), SCHEMA)


def test_api_start_command_parses_and_serves_behind_the_proxy() -> None:
    parts = shlex.split(load("api")["deploy"]["startCommand"])
    assert parts[:2] == ["sh", "-c"]
    inner = parts[2]
    assert "--proxy-headers" in shlex.split(inner)
    assert "$PORT" in inner or "${PORT" in inner


def test_api_requires_the_photos_volume() -> None:
    assert load("api")["deploy"]["requiredMountPath"] == "/data/files"


@pytest.mark.parametrize("name", ["api", "scheduler"])
def test_railway_config_builds_the_shared_dockerfile(name: str) -> None:
    cfg = load(name)
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert (ROOT / cfg["build"]["dockerfilePath"]).is_file()
    assert cfg["deploy"]["numReplicas"] == 1
    assert cfg["deploy"]["restartPolicyType"] == "ON_FAILURE"


def test_api_service() -> None:
    deploy = load("api")["deploy"]
    assert deploy["preDeployCommand"] == ["alembic upgrade head"]
    assert deploy["healthcheckPath"] == "/healthz"
    assert "uvicorn app.main:app" in deploy["startCommand"]
    assert "--proxy-headers" in deploy["startCommand"]
    assert "${PORT" in deploy["startCommand"]


def test_scheduler_service() -> None:
    deploy = load("scheduler")["deploy"]
    assert deploy["startCommand"] == "python -m app.jobs.runner"
    assert "healthcheckPath" not in deploy
    assert "preDeployCommand" not in deploy


def test_dockerignore_excludes_secrets() -> None:
    lines = (ROOT / ".dockerignore").read_text().split()
    assert ".env" in lines
    assert ".env.*" in lines
    assert lines.index("!.env.example") > lines.index(".env.*")


def test_dockerfile_pins_uv_and_storage_dir() -> None:
    text = (ROOT / "backend" / "Dockerfile").read_text()
    assert "uv:latest" not in text
    assert "STORAGE_DIR=/data/files" in text
