import os
import subprocess
import sys
from pathlib import Path

from conftest import ORIGIN
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from test_auth import csrf_headers, login_buyer

from app.config import Settings
from app.db import make_engine


def test_seed_seller_is_idempotent_and_never_promotes_buyer(
    client: TestClient, settings: Settings
) -> None:
    from app.seed import SeedOutcome, seed_seller

    engine = make_engine(settings.database_url.get_secret_value())
    with DBSession(engine) as db:
        first = seed_seller(db, email="Seller@Example.com", password="Demo-seller-2026!")
    assert first.outcome is SeedOutcome.CREATED
    engine.dispose()

    seller_login = client.post(
        "/api/auth/login",
        json={"email": "seller@example.com", "password": "Demo-seller-2026!"},
        headers=csrf_headers(client),
    )
    assert seller_login.status_code == 200
    assert seller_login.json()["user"]["role"] == "seller"
    assert seller_login.json()["user"]["name"] == "Penjual Hanya Roti Biasa"
    assert client.get("/api/seller/profile").status_code == 200

    engine = make_engine(settings.database_url.get_secret_value())
    with DBSession(engine) as db:
        second = seed_seller(db, email="seller@example.com", password="Different-password-2026!")
    engine.dispose()
    assert second.outcome is SeedOutcome.UNCHANGED

    client.post(
        "/api/auth/logout",
        headers={"Origin": ORIGIN, "X-CSRF-Token": seller_login.json()["csrf_token"]},
    )
    old_password = client.post(
        "/api/auth/login",
        json={"email": "seller@example.com", "password": "Demo-seller-2026!"},
        headers=csrf_headers(client),
    )
    new_password = client.post(
        "/api/auth/login",
        json={"email": "seller@example.com", "password": "Different-password-2026!"},
        headers=csrf_headers(client),
    )
    assert old_password.status_code == 200
    assert new_password.status_code == 401

    seller_csrf = client.get("/api/auth/session").json()["csrf_token"]
    assert client.post(
        "/api/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": seller_csrf}
    ).status_code == 204
    login_buyer(client)
    engine = make_engine(settings.database_url.get_secret_value())
    with DBSession(engine) as db:
        refused = seed_seller(db, email="buyer@example.com", password="New-seller-password!")
    engine.dispose()
    assert refused.outcome is SeedOutcome.REFUSED_BUYER
    assert client.get("/api/seller/profile").status_code == 403


def test_seller_seed_cli_is_repeatable(settings: Settings) -> None:
    base_url = settings.database_url.get_secret_value()
    env = {**os.environ, "DATABASE_URL": base_url}
    backend = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "app.seed",
        "--email",
        "cli-seller@example.com",
        "--password",
        "Cli-seller-password-2026!",
    ]
    first = subprocess.run(command, cwd=backend, env=env, capture_output=True, text=True)
    second = subprocess.run(command, cwd=backend, env=env, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    assert "created" in first.stdout.lower()
    assert second.returncode == 0, second.stderr
    assert "unchanged" in second.stdout.lower()
    assert "Cli-seller-password-2026!" not in first.stdout + first.stderr
    assert "Cli-seller-password-2026!" not in second.stdout + second.stderr


def test_seller_seed_takes_password_from_the_environment(
    client: TestClient, settings: Settings
) -> None:
    database_url = settings.database_url
    assert database_url is not None
    password = "Env-seller-password-2026!"
    env = {
        **os.environ,
        "DATABASE_URL": database_url.get_secret_value(),
        "SEED_SELLER_PASSWORD": password,
    }
    backend = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "app.seed", "--email", "env-seller@example.com"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "created" in completed.stdout.lower()
    assert password not in completed.stdout + completed.stderr

    login = client.post(
        "/api/auth/login",
        json={"email": "env-seller@example.com", "password": password},
        headers=csrf_headers(client),
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "seller"


def test_production_seed_refuses_the_development_demo_password(settings: Settings) -> None:
    database_url = settings.database_url
    assert database_url is not None
    env = {
        **os.environ,
        "DATABASE_URL": database_url.get_secret_value(),
        "ENVIRONMENT": "production",
        "ALLOWED_ORIGINS": '["https://wad05-uas.example.run.app"]',
    }
    env.pop("SEED_SELLER_PASSWORD", None)
    backend = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "app.seed", "--email", "prod-seller@example.com"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Refused" in completed.stderr
    assert "Demo-seller-2026!" not in completed.stdout + completed.stderr


def test_production_seed_accepts_an_explicit_secret_password(
    client: TestClient, settings: Settings
) -> None:
    database_url = settings.database_url
    assert database_url is not None
    password = "Explicit-prod-seller-2026!"
    env = {
        **os.environ,
        "DATABASE_URL": database_url.get_secret_value(),
        "ENVIRONMENT": "production",
        "ALLOWED_ORIGINS": '["https://wad05-uas.example.run.app"]',
        "SEED_SELLER_PASSWORD": password,
    }
    backend = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "app.seed", "--email", "explicit-prod-seller@example.com"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "created" in completed.stdout.lower()
    assert password not in completed.stdout + completed.stderr
