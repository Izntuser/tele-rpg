"""`scripts/live.sh check` guard logic. Uses a temp LIVE_ENV_FILE, never the real .env."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "live.sh"

GOOD_URL = "postgresql+asyncpg://postgres.abc:s3cretpw@aws-0.pooler.supabase.com:5432/postgres"
E2E_URL = "postgresql+asyncpg://telerpg:telerpg@localhost:5432/telerpg_e2e"
REAL_TOKEN = "123456789:AAreal-looking-token-value-xyz"
FAKE_TOKEN = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"


def run_check(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / "live.env"
    env_file.write_text("".join(f"{k}='{v}'\n" for k, v in env.items()))
    return subprocess.run(
        ["bash", str(SCRIPT), "check"],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "LIVE_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_passing_config_masks_password(tmp_path: Path) -> None:
    r = run_check(
        tmp_path, DATABASE_URL=GOOD_URL, E2E_DATABASE_URL=E2E_URL, TG_BOT_TOKEN=REAL_TOKEN
    )
    assert r.returncode == 0, r.stderr
    assert "config ok" in r.stdout
    assert "s3cretpw" not in r.stdout + r.stderr
    assert REAL_TOKEN not in r.stdout + r.stderr


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"TG_BOT_TOKEN": REAL_TOKEN}, "DATABASE_URL is not set"),
        (
            {"DATABASE_URL": E2E_URL, "E2E_DATABASE_URL": E2E_URL, "TG_BOT_TOKEN": REAL_TOKEN},
            "E2E_DATABASE_URL",
        ),
        (
            {"DATABASE_URL": E2E_URL, "TG_BOT_TOKEN": REAL_TOKEN},
            "_e2e",
        ),
        ({"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": FAKE_TOKEN}, "fake dev token"),
        (
            {"DATABASE_URL": GOOD_URL.replace("+asyncpg", ""), "TG_BOT_TOKEN": REAL_TOKEN},
            "+asyncpg",
        ),
        (
            {
                "DATABASE_URL": GOOD_URL.replace("postgresql+asyncpg", "postgres"),
                "TG_BOT_TOKEN": REAL_TOKEN,
            },
            "+asyncpg",
        ),
        (
            {"DATABASE_URL": GOOD_URL.replace(":5432", ":6543"), "TG_BOT_TOKEN": REAL_TOKEN},
            "6543",
        ),
    ],
)
def test_refusals(tmp_path: Path, env: dict[str, str], message: str) -> None:
    r = run_check(tmp_path, **env)
    assert r.returncode != 0
    assert message in r.stderr
    assert "s3cretpw" not in r.stdout + r.stderr
