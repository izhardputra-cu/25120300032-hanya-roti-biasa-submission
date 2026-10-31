import pytest
from conftest import ORIGIN
from fastapi.testclient import TestClient

from app.config import Settings

BUYER = {"name": "Demo Buyer", "email": "buyer@example.com", "password": "Synthetic-buyer-2026!"}


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/auth/session").json()["csrf_token"]
    return {"Origin": ORIGIN, "X-CSRF-Token": token}


def test_bootstrap_reuses_anonymous_session(client: TestClient) -> None:
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json()["user"] is None
    assert len(response.json()["csrf_token"]) >= 32
    cookie = client.cookies["wad05_session"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert "Max-Age=86400" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    again = client.get("/api/auth/session")
    assert again.json() == response.json()
    assert client.cookies["wad05_session"] == cookie


def test_register_creates_buyer_without_logging_in(client: TestClient) -> None:
    headers = csrf_headers(client)
    response = client.post("/api/auth/register", json=BUYER, headers=headers)
    assert response.status_code == 201
    user = response.json()["user"]
    assert user == {
        "id": user["id"],
        "name": "Demo Buyer",
        "email": "buyer@example.com",
        "role": "buyer",
    }
    assert isinstance(user["id"], int)
    assert client.get("/api/auth/session").json() == {
        "user": None,
        "csrf_token": headers["X-CSRF-Token"],
    }
    assert BUYER["password"] not in response.text


@pytest.mark.parametrize(
    "failure",
    ["missing-token", "wrong-token", "wrong-origin", "missing-origin", "no-session"],
)
def test_register_rejects_csrf_and_origin_failures(client: TestClient, failure: str) -> None:
    headers = csrf_headers(client)
    if failure == "missing-token":
        del headers["X-CSRF-Token"]
    elif failure == "wrong-token":
        headers["X-CSRF-Token"] = "0" * 64
    elif failure == "wrong-origin":
        headers["Origin"] = "https://evil.example"
    elif failure == "missing-origin":
        del headers["Origin"]
    else:
        client.cookies.clear()
    response = client.post("/api/auth/register", json=BUYER, headers=headers)
    assert response.status_code == 403


@pytest.mark.parametrize("action", ["register", "login", "logout"])
def test_non_ascii_csrf_is_rejected_without_server_error(
    client: TestClient, action: str
) -> None:
    login = login_buyer(client)
    headers = {b"Origin": ORIGIN.encode("ascii"), b"X-CSRF-Token": b"caf\xe9"}
    payload = BUYER if action == "register" else {
        "email": BUYER["email"], "password": BUYER["password"]
    }
    response = client.post(f"/api/auth/{action}", json=payload, headers=headers)
    assert response.status_code == 403
    assert client.get("/api/me").json() == login["user"]


def register_buyer(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/register", json=BUYER, headers=csrf_headers(client))
    assert response.status_code == 201
    return response.json()["user"]


def test_login_rotates_anonymous_session_and_returns_buyer(client: TestClient) -> None:
    register_buyer(client)
    anonymous_cookie = client.cookies["wad05_session"]
    anonymous_csrf = client.get("/api/auth/session").json()["csrf_token"]
    headers = csrf_headers(client)

    response = client.post(
        "/api/auth/login",
        json={"email": "BUYER@Example.com", "password": BUYER["password"]},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "buyer"
    assert body["user"]["email"] == "buyer@example.com"
    assert body["csrf_token"] != anonymous_csrf
    assert client.cookies["wad05_session"] != anonymous_cookie
    assert client.get("/api/auth/session").json()["user"] == body["user"]


@pytest.mark.parametrize("password", ["short-pass", "x" * 129])
def test_login_rejects_password_outside_bounds_without_echoing_it(
    client: TestClient, password: str
) -> None:
    register_buyer(client)
    response = client.post(
        "/api/auth/login",
        json={"email": BUYER["email"], "password": password},
        headers=csrf_headers(client),
    )
    assert response.status_code == 422
    assert password not in response.text
    assert client.get("/api/auth/session").json()["user"] is None


def test_login_rejects_wrong_password_and_unknown_email_generically(client: TestClient) -> None:
    register_buyer(client)
    headers = csrf_headers(client)
    anonymous_cookie = client.cookies["wad05_session"]

    wrong_password = client.post(
        "/api/auth/login",
        json={"email": BUYER["email"], "password": "Wrong-password-2026!"},
        headers=headers,
    )
    unknown_email = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": BUYER["password"]},
        headers=headers,
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert BUYER["password"] not in wrong_password.text
    assert client.cookies["wad05_session"] == anonymous_cookie
    assert client.get("/api/auth/session").json()["user"] is None


@pytest.mark.parametrize(
    "failure", ["missing-token", "wrong-token", "wrong-origin", "missing-origin"]
)
def test_login_rejects_csrf_and_origin_failures(client: TestClient, failure: str) -> None:
    register_buyer(client)
    headers = csrf_headers(client)
    if failure == "missing-token":
        del headers["X-CSRF-Token"]
    elif failure == "wrong-token":
        headers["X-CSRF-Token"] = "0" * 64
    elif failure == "wrong-origin":
        headers["Origin"] = "https://evil.example"
    else:
        del headers["Origin"]

    response = client.post(
        "/api/auth/login",
        json={"email": BUYER["email"], "password": BUYER["password"]},
        headers=headers,
    )

    assert response.status_code == 403
    assert client.get("/api/auth/session").json()["user"] is None


def test_prelogin_cookie_is_invalid_after_login_rotation(client: TestClient) -> None:
    register_buyer(client)
    old_cookie = client.cookies["wad05_session"]
    headers = csrf_headers(client)
    assert client.post(
        "/api/auth/login",
        json={"email": BUYER["email"], "password": BUYER["password"]},
        headers=headers,
    ).status_code == 200

    client.cookies.clear()
    client.cookies.set("wad05_session", old_cookie)
    replay = client.get("/api/auth/session")
    assert replay.status_code == 200
    assert replay.json()["user"] is None
    assert client.get("/api/me").status_code == 401


def login_buyer(client: TestClient) -> dict[str, object]:
    register_buyer(client)
    headers = csrf_headers(client)
    response = client.post(
        "/api/auth/login",
        json={"email": BUYER["email"], "password": BUYER["password"]},
        headers=headers,
    )
    assert response.status_code == 200
    return {**headers, **response.json()}


def test_logout_revokes_session_and_old_cookie_cannot_be_replayed(client: TestClient) -> None:
    login = login_buyer(client)
    logged_in_cookie = client.cookies["wad05_session"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": str(login["csrf_token"])}

    response = client.post("/api/auth/logout", headers=headers)

    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    client.cookies.clear()
    client.cookies.set("wad05_session", logged_in_cookie)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/auth/session").json()["user"] is None


@pytest.mark.parametrize(
    "failure", ["missing-token", "wrong-token", "wrong-origin", "missing-origin"]
)
def test_logout_rejects_csrf_and_origin_failures(client: TestClient, failure: str) -> None:
    login = login_buyer(client)
    headers = {"Origin": ORIGIN, "X-CSRF-Token": str(login["csrf_token"])}
    if failure == "missing-token":
        del headers["X-CSRF-Token"]
    elif failure == "wrong-token":
        headers["X-CSRF-Token"] = "0" * 64
    elif failure == "wrong-origin":
        headers["Origin"] = "https://evil.example"
    else:
        del headers["Origin"]

    assert client.post("/api/auth/logout", headers=headers).status_code == 403
    assert client.get("/api/me").status_code == 200


def test_me_and_seller_profile_enforce_authentication_and_role(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/seller/profile").status_code == 401

    login = login_buyer(client)
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == login["user"]
    denied = client.get("/api/seller/profile")
    assert denied.status_code == 403
    assert "password" not in denied.text.lower()


def test_register_rejects_duplicate_email_after_normalization(client: TestClient) -> None:
    register_buyer(client)
    headers = csrf_headers(client)
    duplicate = client.post(
        "/api/auth/register",
        json={**BUYER, "email": "  BUYER@EXAMPLE.COM  ", "name": "Second Buyer"},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert BUYER["password"] not in duplicate.text


def test_register_rejects_forged_role_and_invalid_fields_without_echoing_password(
    client: TestClient,
) -> None:
    headers = csrf_headers(client)
    forged = client.post(
        "/api/auth/register", json={**BUYER, "role": "seller"}, headers=headers
    )
    assert forged.status_code == 422

    short_password = "short-pass"
    invalid_password = client.post(
        "/api/auth/register",
        json={**BUYER, "email": "short@example.com", "password": short_password},
        headers=headers,
    )
    assert invalid_password.status_code == 422
    assert short_password not in invalid_password.text

    invalid_email = client.post(
        "/api/auth/register",
        json={**BUYER, "email": "not-an-email"},
        headers=headers,
    )
    assert invalid_email.status_code == 422
    assert BUYER["password"] not in invalid_email.text

    blank_name = client.post(
        "/api/auth/register",
        json={**BUYER, "email": "blank@example.com", "name": " "},
        headers=headers,
    )
    assert blank_name.status_code == 422
    assert client.get("/api/auth/session").json()["user"] is None


def test_session_expires_after_fixed_24_hours_without_sleep(
    clocked_client: tuple[TestClient, object],
) -> None:
    from datetime import timedelta

    client, clock = clocked_client
    register_buyer(client)
    headers = csrf_headers(client)
    login = client.post(
        "/api/auth/login",
        json={"email": BUYER["email"], "password": BUYER["password"]},
        headers=headers,
    )
    assert login.status_code == 200
    assert client.get("/api/me").status_code == 200

    clock.now += timedelta(hours=24) - timedelta(seconds=1)  # type: ignore[attr-defined]
    assert client.get("/api/me").status_code == 200

    clock.now += timedelta(seconds=2)  # type: ignore[attr-defined]
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/auth/session").json()["user"] is None


def test_invalid_session_cookie_is_ignored_and_replaced(client: TestClient) -> None:
    client.cookies.set("wad05_session", "not-a-real-token")
    assert client.get("/api/me").status_code == 401
    session = client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.json()["user"] is None
    assert len(session.json()["csrf_token"]) >= 32
    assert "set-cookie" in session.headers


def test_production_session_cookie_is_secure(settings: Settings) -> None:
    from app.main import create_app

    production = Settings(
        database_url=settings.database_url,
        environment="production",
        allowed_origins=["https://wad05-uas.example.run.app"],
    )
    with TestClient(create_app(production)) as client:
        response = client.get("/api/auth/session")
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
