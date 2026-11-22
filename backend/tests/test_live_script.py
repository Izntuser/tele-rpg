"""`scripts/live.sh check` guard logic. Uses a temp LIVE_ENV_FILE, never the real .env."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "live.sh"

GOOD_URL = "postgresql+asyncpg://postgres.abc:s3cretpw@aws-0.pooler.supabase.com:5432/postgres"
E2E_URL = "postgresql+asyncpg://telerpg:telerpg@localhost:5432/telerpg_e2e"
REAL_TOKEN = "123456789:AAreal-looking-token-value-xyz"
JWT = "0123456789abcdef0123456789abcdef0123456789abcdef-jwt-secret"
FAKE_TOKEN = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE"


def run_check(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    env.setdefault("JWT_SECRET", JWT)
    env_file = tmp_path / "live.env"
    env_file.write_text("".join(f"{k}='{v}'\n" for k, v in env.items()))
    return run_raw(tmp_path, env_file)


def run_raw(
    tmp_path: Path, env_file: Path, *args: str, bash_flags: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", *bash_flags, str(SCRIPT), *(args or ("check",))],
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


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_plain_postgres_scheme_passes(tmp_path: Path, scheme: str) -> None:
    url = GOOD_URL.replace("postgresql+asyncpg", scheme)
    r = run_check(tmp_path, DATABASE_URL=url, TG_BOT_TOKEN=REAL_TOKEN)
    assert r.returncode == 0, r.stderr


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
        ({"DATABASE_URL": "mysql://u:p@h/db", "TG_BOT_TOKEN": REAL_TOKEN}, "must start with"),
        (
            {"DATABASE_URL": GOOD_URL.replace(":5432", ":6543"), "TG_BOT_TOKEN": REAL_TOKEN},
            "6543",
        ),
        (
            {"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": REAL_TOKEN, "JWT_SECRET": ""},
            "JWT_SECRET is not set",
        ),
        (
            {
                "DATABASE_URL": GOOD_URL,
                "TG_BOT_TOKEN": REAL_TOKEN,
                "JWT_SECRET": "dev-jwt-secret-change-me",
            },
            "dev default",
        ),
        (
            {"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": REAL_TOKEN, "JWT_SECRET": "short-secret"},
            "shorter than 32",
        ),
        (
            {"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": REAL_TOKEN, "LIVE_API_PORT": "80a"},
            "must be a number",
        ),
        (
            {"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": REAL_TOKEN, "LIVE_WEB_PORT": "$(id)"},
            "must be a number",
        ),
        (
            {"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": REAL_TOKEN, "LIVE_API_PORT": "8000"},
            "test stack",
        ),
        (
            {"DATABASE_URL": GOOD_URL, "TG_BOT_TOKEN": REAL_TOKEN, "LIVE_WEB_PORT": "3000"},
            "test stack",
        ),
        (
            {
                "DATABASE_URL": GOOD_URL,
                "TG_BOT_TOKEN": REAL_TOKEN,
                "LIVE_API_PORT": "9000",
                "LIVE_WEB_PORT": "9000",
            },
            "equal",
        ),
    ],
)
def test_refusals(tmp_path: Path, env: dict[str, str], message: str) -> None:
    r = run_check(tmp_path, **env)
    assert r.returncode != 0
    assert message in r.stderr
    assert "s3cretpw" not in r.stdout + r.stderr


def test_env_file_is_parsed_not_executed(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    pw = f"p$a&s@s:w`touch {marker}`$(touch {marker}){{x}}"
    env_file = tmp_path / "live.env"
    env_file.write_text(
        "# comment\n\n"
        f'DATABASE_URL="postgresql+asyncpg://u:{pw}@host.example.com:5432/postgres"\n'
        f"TG_BOT_TOKEN={REAL_TOKEN}\n"
        f"export JWT_SECRET='{JWT}'\n"
        f"UNRELATED=$(touch {marker})\n"
    )
    r = run_raw(tmp_path, env_file)
    assert r.returncode == 0, r.stderr
    assert not marker.exists()
    assert "config ok" in r.stdout
    out = r.stdout + r.stderr
    assert "p$a" not in out
    assert "****@host.example.com" in out


def test_values_taken_literally(tmp_path: Path) -> None:
    env_file = tmp_path / "live.env"
    # unquoted $ would abort a sourced file under set -u; here it is a literal
    env_file.write_text(
        f"DATABASE_URL=postgresql+asyncpg://u:$HOME&x@h:5432/db\n"
        f"TG_BOT_TOKEN={REAL_TOKEN}\nJWT_SECRET={JWT}\n"
    )
    r = run_raw(tmp_path, env_file, "status")
    assert r.returncode == 0, r.stderr
    assert "db postgresql+asyncpg://u:****@h:5432/db" in r.stdout
    assert "&x" not in r.stdout


def test_mask_url_raw_at_and_colon(tmp_path: Path) -> None:
    url = "postgresql+asyncpg://user:pa@ss:wo@rd@db.example.com:5432/postgres"
    r = run_check(tmp_path, DATABASE_URL=url, TG_BOT_TOKEN=REAL_TOKEN)
    assert r.returncode == 0, r.stderr
    assert "user:****@db.example.com:5432/postgres" in r.stdout
    for frag in ("pa@ss", "wo@rd", "ss:wo"):
        assert frag not in r.stdout + r.stderr


def test_xtrace_hides_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / "live.env"
    env_file.write_text(f"DATABASE_URL={GOOD_URL}\nTG_BOT_TOKEN={REAL_TOKEN}\nJWT_SECRET={JWT}\n")
    r = run_raw(tmp_path, env_file, "check", bash_flags=("-x",))
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    for secret in (REAL_TOKEN, JWT, "s3cretpw", "AAreal-looking"):
        assert secret not in out


def test_stop_does_not_kill_reused_pid(tmp_path: Path) -> None:
    """A pidfile pointing at an unrelated live process is stale: removed, process untouched."""
    import shutil
    import signal

    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    (work / "logs").mkdir()
    shutil.copy(SCRIPT, work / "scripts" / "live.sh")
    victim = subprocess.Popen(["sleep", "30"])
    try:
        for n in ("live-api", "live-web", "live-bot", "live-sched"):
            (work / "logs" / f"{n}.pid").write_text(str(victim.pid))
        r = subprocess.run(
            ["bash", str(work / "scripts" / "live.sh"), "stop"],
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "LIVE_ENV_FILE": str(tmp_path / "none")},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert r.returncode == 0, r.stderr
        assert "not killing" in r.stdout
        assert victim.poll() is None
        assert not list((work / "logs").glob("*.pid"))
    finally:
        victim.send_signal(signal.SIGKILL)
        victim.wait()
