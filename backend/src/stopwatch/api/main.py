"""FastAPI application factory for the dynamic API (``/api/v1``, docs/contracts.md §4).

Run locally with ``uvicorn stopwatch.api.main:app``; in AWS the same app is wrapped by Mangum
(:mod:`stopwatch.api.lambda_handler`).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from stopwatch.platform.blobstore import open_blobstore
from stopwatch.platform.config import Settings, get_settings

from .errors import install_error_handlers
from .middleware import CrossSiteRequestMiddleware, OriginVerifyMiddleware, RequestContextMiddleware
from .routes import alerts, ask, auth, commutes, config, health, me, push

API_PREFIX = "/api/v1"


def _mount_local_site_data(app: FastAPI, settings: Settings) -> None:
    """Serve the local site store's ``data/`` at ``/data`` for the Vite dev proxy (CloudFront in AWS)."""
    if settings.env not in ("local", "test") or not settings.site_url.startswith("file://"):
        return
    data_dir = open_blobstore(settings.site_url).local_path("data")
    if data_dir is None:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/data", StaticFiles(directory=data_dir), name="site-data")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    interactive_docs = settings.env in ("local", "test")
    app = FastAPI(
        title="Stopwatch API",
        version=settings.version,
        openapi_url=f"{API_PREFIX}/openapi.json" if interactive_docs else None,
        docs_url=f"{API_PREFIX}/docs" if interactive_docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    for module in (health, config, auth, me, commutes, alerts, push, ask):
        app.include_router(module.router, prefix=API_PREFIX)
    install_error_handlers(app)
    # Added inner-first: RequestContext wraps everything, so even CSRF rejections carry X-Request-Id.
    app.add_middleware(CrossSiteRequestMiddleware, settings=settings)
    app.add_middleware(OriginVerifyMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware, settings=settings)
    _mount_local_site_data(app, settings)
    return app


app = create_app()
