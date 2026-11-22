import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "backend" / "Dockerfile").read_text()


def test_dockerignore_excludes_secrets() -> None:
    lines = (ROOT / ".dockerignore").read_text().split()
    assert ".env" in lines
    assert ".env.*" in lines
    assert lines.index("!.env.example") > lines.index(".env.*")


def test_dockerfile_cmd_serves_behind_the_proxy_on_port() -> None:
    cmd = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD"))
    assert "uvicorn app.main:app" in cmd
    assert "${PORT" in cmd
    assert "--proxy-headers" in cmd
    assert "--forwarded-allow-ips" in cmd


def test_dockerfile_pins_uv_and_storage_dir() -> None:
    assert "uv:latest" not in DOCKERFILE
    assert re.search(r"astral-sh/uv:\d+\.\d+\.\d+ ", DOCKERFILE)
    assert "STORAGE_DIR=/data/files" in DOCKERFILE
