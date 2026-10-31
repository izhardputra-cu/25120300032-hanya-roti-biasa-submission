from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import sessionmaker

from app.auth import router
from app.catalog import public_router, seller_router
from app.config import Settings
from app.db import make_engine
from app.fulfillment import router as fulfillment_router
from app.orders import router as order_router
from app.schedules import public_router as schedule_public_router
from app.schedules import seller_router as schedule_seller_router
from app.security import utc_now

# Paths that always belong to the API (or its documentation), never to the SPA.
RESERVED_PREFIXES = ("/api", "/docs", "/redoc", "/openapi.json")


def _accepts_html(accept: str) -> bool:
    for part in accept.split(","):
        media_type, *parameters = (item.strip() for item in part.split(";"))
        if media_type.lower() not in {"text/html", "application/xhtml+xml"}:
            continue
        quality = 1.0
        for parameter in parameters:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality > 0:
            return True
    return False


def _is_spa_navigation(request: Request) -> bool:
    """Only browser navigation to an app path may fall back to index.html.

    API paths, documentation, and anything that looks like a file (missing
    assets, `.env`, source files) keep a JSON 404 instead of an HTML page.
    """
    if request.method not in ("GET", "HEAD"):
        return False
    path = request.url.path
    for prefix in RESERVED_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return False
    if "." in path.rsplit("/", 1)[-1]:
        return False
    return _accepts_html(request.headers.get("accept", ""))


def create_app(
    settings: Settings | None = None, clock: Callable[[], datetime] = utc_now
) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.sqlalchemy_url())
    docs_enabled = settings.api_docs_enabled()
    frontend_index = (
        Path(settings.frontend_dir) / "index.html" if settings.frontend_dir else None
    )
    if frontend_index is not None and not frontend_index.is_file():
        raise RuntimeError(
            f"Frontend build is missing index.html in {settings.frontend_dir}"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        debug=False,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep submitted values (especially passwords) out of validation responses.
        errors = [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors}
        )

    @app.exception_handler(status.HTTP_404_NOT_FOUND)
    async def not_found(request: Request, _exc: Exception) -> JSONResponse | FileResponse:
        if frontend_index is not None and _is_spa_navigation(request):
            return FileResponse(
                frontend_index,
                media_type="text/html",
                headers={"Cache-Control": "no-cache"},
            )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not Found"}
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(public_router)
    app.include_router(seller_router)
    app.include_router(schedule_public_router)
    app.include_router(schedule_seller_router)
    app.include_router(order_router)
    app.include_router(fulfillment_router)
    if settings.frontend_dir is not None:
        # Static files only; the 404 handler above serves index.html for SPA
        # navigation, so /api and asset paths are never replaced by the app.
        app.frontend("/", directory=settings.frontend_dir, fallback=None, check_dir=True)
    return app
