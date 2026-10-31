import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import Settings

APP_ORIGIN = "https://wad05-uas-25120300032-56155567170.asia-southeast2.run.app"
CONNECTION_NAME = "wad05-uas-25120300032:asia-southeast2:wad05-mysql"


def test_cloud_sql_components_build_an_encoded_socket_url(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    configured = Settings(
        environment="production",
        allowed_origins=[APP_ORIGIN],
        db_user="wad05_app",
        db_password="Cloud-sql pass:with/punctuation?#%[]",
        db_name="wad05",
        cloudsql_connection_name=CONNECTION_NAME,
    )

    url = make_url(configured.sqlalchemy_url())

    assert url.drivername == "mysql+pymysql"
    assert url.username == "wad05_app"
    assert url.password == "Cloud-sql pass:with/punctuation?#%[]"
    assert url.database == "wad05"
    assert url.host is None
    assert url.port is None
    assert url.query["unix_socket"] == f"/cloudsql/{CONNECTION_NAME}"
    assert url.query["charset"] == "utf8mb4"
    assert "Cloud-sql pass" not in repr(url)


def test_database_configuration_requires_exactly_one_mode(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(environment="test")
    with pytest.raises(ValidationError, match="DB_PASSWORD"):
        Settings(environment="test", db_user="wad05_app")
    with pytest.raises(ValidationError, match="not both"):
        Settings(database_url=settings.database_url, db_user="wad05_app")


def test_development_settings_keep_local_api_docs() -> None:
    settings = Settings(environment="test", database_url="mysql+pymysql://user:pass@db/app")
    assert settings.api_docs_enabled() is True
    assert settings.secure_cookies() is False


def test_api_docs_can_be_forced_off_outside_production() -> None:
    settings = Settings(
        environment="test",
        database_url="mysql+pymysql://user:pass@db/app",
        enable_api_docs=False,
    )
    assert settings.api_docs_enabled() is False
