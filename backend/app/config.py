from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class Settings(BaseSettings):
    """Runtime configuration for development, tests, and the cloud container.

    Local development and tests use `DATABASE_URL`. The container uses the
    separate components below and builds the SQLAlchemy URL with
    `URL.create`, so a password with URL punctuation never has to be escaped
    by hand. Cloud Run reaches Cloud SQL through its Unix socket.
    """

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr | None = None
    db_user: str | None = None
    db_password: SecretStr | None = None
    db_name: str | None = None
    cloudsql_connection_name: str | None = None
    environment: Literal["development", "test", "production"] = "development"
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cookie_secure: bool = False
    frontend_dir: str | None = None
    enable_api_docs: bool | None = None

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> Self:
        component_values = (
            self.db_user,
            self.db_password,
            self.db_name,
            self.cloudsql_connection_name,
        )
        if self.database_url is None:
            missing = [
                name
                for name, value in zip(
                    ("DB_USER", "DB_PASSWORD", "DB_NAME", "CLOUDSQL_CONNECTION_NAME"),
                    component_values,
                    strict=True,
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Set DATABASE_URL or all of " + ", ".join(missing) + " for the database"
                )
        elif any(value is not None for value in component_values):
            raise ValueError("Set either DATABASE_URL or the DB_* components, not both")
        if self.environment == "production":
            self._validate_production_origins()
        return self

    def _validate_production_origins(self) -> None:
        """Production serves one same-origin HTTPS app, never a wildcard or localhost."""
        if not self.allowed_origins:
            raise ValueError("Production requires the HTTPS origin of the deployed app")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.hostname in LOCAL_HOSTNAMES
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Production ALLOWED_ORIGINS must be the actual https:// service origin"
                )

    def secure_cookies(self) -> bool:
        """Production never ships a session cookie without HTTPS-only delivery."""
        return self.cookie_secure or self.environment == "production"

    def api_docs_enabled(self) -> bool:
        """Keep /docs and /openapi.json out of the public production service."""
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return self.environment != "production"

    def sqlalchemy_url(self) -> str:
        """Return a driver URL, either explicit or built for a Cloud SQL socket.

        `URL.create` percent-encodes the username, password, and socket path.
        `make_engine` rebuilds the URL with SQLAlchemy's parser, so credentials
        are never interpolated into a URL string by hand.
        """
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        if (
            self.db_user is None
            or self.db_password is None
            or self.db_name is None
            or self.cloudsql_connection_name is None
        ):
            raise ValueError("Cloud SQL socket configuration is incomplete")
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            database=self.db_name,
            query={
                "charset": "utf8mb4",
                "unix_socket": f"/cloudsql/{self.cloudsql_connection_name}",
            },
        ).render_as_string(hide_password=False)
