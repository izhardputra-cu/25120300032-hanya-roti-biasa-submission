"""Same-origin production routing for the built Vue app.

The build output is mimicked with a tiny directory so routing is tested
deterministically; the real `frontend/dist` is exercised by the production
Playwright run documented in docs/testing/t2-frontend.md.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

INDEX_MARKER = '<div id="app"></div>'
HTML = {"Accept": "text/html"}


@pytest.fixture
def built_frontend(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body>"
        f'{INDEX_MARKER}<script type="module" src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">'
        "</body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log('demo')\n", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("body{color:#2b2118}\n", encoding="utf-8")
    (tmp_path / "private.txt").write_text("TOP-SECRET-OUTSIDE-BUILD", encoding="utf-8")
    return dist


@pytest.fixture
def frontend_client(settings: Settings, built_frontend: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(settings.model_copy(update={"frontend_dir": str(built_frontend)}))
    ) as client:
        yield client


def test_built_frontend_is_served_with_spa_deep_links(frontend_client: TestClient) -> None:
    root = frontend_client.get("/", headers=HTML)
    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert INDEX_MARKER in root.text

    for path in ("/masuk", "/daftar", "/akun", "/penjual"):
        page = frontend_client.get(path, headers=HTML)
        assert page.status_code == 200, path
        assert page.headers["content-type"].startswith("text/html")
        assert page.text == root.text

    script = frontend_client.get("/assets/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    stylesheet = frontend_client.get("/assets/app.css")
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")

    head = frontend_client.head("/akun", headers=HTML)
    assert head.status_code == 200
    assert head.content == b""


@pytest.mark.parametrize("path", ["/api/missing", "/api/missing/child", "/api"])
@pytest.mark.parametrize("accept", ["text/html", "application/json", "*/*"])
def test_unknown_api_paths_never_return_html(
    frontend_client: TestClient, path: str, accept: str
) -> None:
    response = frontend_client.get(path, headers={"Accept": accept})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("path", ["/assets/missing.js", "/assets/missing.css", "/favicon.ico"])
def test_missing_assets_stay_404_for_html_clients(
    frontend_client: TestClient, path: str
) -> None:
    response = frontend_client.get(path, headers=HTML)
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_wrong_methods_keep_json_errors_instead_of_html_fallback(
    frontend_client: TestClient,
) -> None:
    wrong_method = frontend_client.get("/api/auth/login", headers=HTML)
    assert wrong_method.status_code == 405
    assert wrong_method.headers["content-type"].startswith("application/json")

    unsupported = frontend_client.put("/api/auth/login", headers=HTML)
    assert unsupported.status_code == 405
    assert unsupported.headers["content-type"].startswith("application/json")

    page_post = frontend_client.post("/masuk", headers=HTML)
    assert page_post.status_code in (404, 405)
    assert not page_post.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.env.example",
        "/backend/app/main.py",
        "/frontend/src/main.js",
        "/docs/plans/t2-cloud-login.md",
        "/private.txt",
        "/assets/../../private.txt",
        "/assets/%2e%2e/%2e%2e/private.txt",
    ],
)
def test_private_files_and_traversal_are_not_served(
    frontend_client: TestClient, path: str
) -> None:
    response = frontend_client.get(path, headers=HTML)
    assert response.status_code == 404
    assert "TOP-SECRET-OUTSIDE-BUILD" not in response.text
    assert "DATABASE_URL" not in response.text


def test_api_routes_take_priority_over_the_frontend(frontend_client: TestClient) -> None:
    health = frontend_client.get("/api/health", headers=HTML)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert health.headers["content-type"].startswith("application/json")


def test_missing_frontend_build_fails_fast(settings: Settings, tmp_path: Path) -> None:
    empty = tmp_path / "dist-without-index"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="index.html"):
        create_app(settings.model_copy(update={"frontend_dir": str(empty)}))


def test_api_only_app_returns_json_404_without_a_frontend_build(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/akun", headers=HTML)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")


def _production_settings(settings: Settings, origins: list[str]) -> Settings:
    database_url = settings.database_url
    assert database_url is not None
    return Settings(
        database_url=database_url,
        environment="production",
        allowed_origins=origins,
        frontend_dir=None,
    )


def test_production_requires_an_https_app_origin(settings: Settings) -> None:
    production = _production_settings(settings, ["https://wad05-uas.example.run.app"])
    assert production.secure_cookies() is True
    assert production.api_docs_enabled() is False


@pytest.mark.parametrize(
    "origins",
    [
        ["http://localhost:5173"],
        ["http://127.0.0.1:8080"],
        ["*"],
        ["https://app.example/"],
        [],
    ],
)
def test_production_rejects_unsafe_origins(settings: Settings, origins: list[str]) -> None:
    with pytest.raises(ValueError):
        _production_settings(settings, origins)


def test_production_disables_api_docs_for_the_public_service(settings: Settings) -> None:
    production = _production_settings(settings, ["https://wad05-uas.example.run.app"])
    with TestClient(create_app(production)) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = client.get(path, headers=HTML)
            assert response.status_code == 404, path
            assert not response.headers["content-type"].startswith("text/html")
