from contextlib import asynccontextmanager
import gc
import logging
import resource
import sys
import threading
from threading import Thread
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings
from app.db import init_db
from app.scheduler import build_scheduler
from app.services.events import listener_count

logger = logging.getLogger(__name__)


def _process_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(rss / (1024 * 1024), 2)
    return round(rss / 1024, 2)


def _normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    stripped = value.strip().rstrip("/")
    return stripped or None


def _cors_allow_origins() -> list[str]:
    configured = [_normalize_origin(origin) for origin in settings.cors_origins]
    frontend_origin = _normalize_origin(settings.frontend_base_url)
    origins = [origin for origin in configured if origin]
    if frontend_origin and frontend_origin not in origins:
        origins.append(frontend_origin)
    return origins


def _cors_allow_origin_regex() -> str | None:
    frontend_origin = _normalize_origin(settings.frontend_base_url)
    if frontend_origin and frontend_origin.endswith(".vercel.app"):
        return r"https://.*\.vercel\.app"
    return None


def _initialize_runtime(app: FastAPI) -> None:
    try:
        logger.info("Starting background runtime initialization")
        init_db()
        app.state.db_ready = True
        logger.info("Database initialization complete")

        if settings.enable_scheduler:
            scheduler = build_scheduler(background=True)
            scheduler.start()
            app.state.scheduler = scheduler
            logger.info("Scheduler started")

        app.state.runtime_ready = True
    except Exception as exc:  # pragma: no cover - deployment/runtime behavior
        app.state.startup_error = str(exc)
        logger.exception("Background runtime initialization failed")


class ReadinessGateMiddleware(BaseHTTPMiddleware):
    """Return 503 for non-health requests until the runtime is ready."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path != "/health" and not getattr(request.app.state, "runtime_ready", False):
            return JSONResponse(
                status_code=503,
                content={"detail": "Service starting up"},
                headers={"Retry-After": "5"},
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scheduler = None
    app.state.db_ready = False
    app.state.runtime_ready = False
    app.state.startup_error = None

    startup_thread = Thread(target=_initialize_runtime, args=(app,), daemon=True, name="runtime-initializer")
    startup_thread.start()
    try:
        yield
    finally:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            scheduler.shutdown(wait=True)
        gc.collect()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(ReadinessGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_origin_regex=_cors_allow_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
def healthcheck() -> dict[str, str | bool | int | float | None]:
    startup_error = getattr(app.state, "startup_error", None)
    runtime_ready = getattr(app.state, "runtime_ready", False)
    db_ready = getattr(app.state, "db_ready", False)
    return {
        "status": "ok" if not startup_error else "degraded",
        "ready": runtime_ready,
        "db_ready": db_ready,
        "scheduler_enabled": settings.enable_scheduler,
        "event_stream_enabled": settings.enable_event_stream,
        "event_listener_count": listener_count(),
        "rss_mb": _process_rss_mb(),
        "thread_count": threading.active_count(),
        "startup_error": startup_error,
    }
