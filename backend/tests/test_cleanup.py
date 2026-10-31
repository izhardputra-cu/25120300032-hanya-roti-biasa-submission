import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from conftest import MutableClock
from fastapi.testclient import TestClient
from test_auth import BUYER, login_buyer

from app.config import Settings


def run_cleanup(settings: Settings) -> subprocess.CompletedProcess[str]:
    database_url = settings.database_url
    assert database_url is not None
    env = {**os.environ, "DATABASE_URL": database_url.get_secret_value()}
    backend = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-m", "app.cleanup", "sessions"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )


def test_cleanup_cli_deletes_only_expired_sessions(
    client: TestClient, clocked_client: tuple[TestClient, MutableClock], settings: Settings
) -> None:
    login_buyer(client)
    logged_in_cookie = client.cookies["wad05_session"]
    assert client.get("/api/me").status_code == 200

    expired_client, clock = clocked_client
    clock.now = datetime(2020, 1, 1, 0, 0, 0)
    assert expired_client.get("/api/auth/session").status_code == 200

    first = run_cleanup(settings)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == "Deleted 1 expired session(s)."
    database_url = settings.database_url
    assert database_url is not None
    assert database_url.get_secret_value() not in first.stdout + first.stderr
    assert BUYER["password"] not in first.stdout + first.stderr

    # The live session row survived, so the buyer stays signed in.
    assert client.get("/api/me").json()["email"] == BUYER["email"]
    assert client.cookies["wad05_session"] == logged_in_cookie

    second = run_cleanup(settings)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "Deleted 0 expired session(s)."


def test_cleanup_cli_redacts_secrets_in_invalid_configuration() -> None:
    marker = "SYNTHETIC_CONFIG_SECRET"
    database_keys = {
        "DATABASE_URL", "DB_USER", "DB_PASSWORD", "DB_NAME", "CLOUDSQL_CONNECTION_NAME"
    }
    env = {key: value for key, value in os.environ.items() if key.upper() not in database_keys}
    env["DB_PASSWORD"] = marker
    completed = subprocess.run(
        [sys.executable, "-m", "app.cleanup", "sessions"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "DB_USER" in completed.stderr
    assert marker not in completed.stdout + completed.stderr


def test_cleanup_cli_requires_an_operational_target(settings: Settings) -> None:
    database_url = settings.database_url
    assert database_url is not None
    env = {**os.environ, "DATABASE_URL": database_url.get_secret_value()}
    backend = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "app.cleanup"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "sessions" in completed.stderr
