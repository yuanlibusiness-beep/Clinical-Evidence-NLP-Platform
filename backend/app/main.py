"""FastAPI application factory.

Responsibilities kept here and nowhere else: lifespan (schema bootstrap and
tracing), CORS, the request-id middleware, the global exception handlers, and
router registration.  Business logic lives behind the routers.

The catch-all exception handler is deliberate.  An unhandled error should return
a JSON body carrying the request id -- so a user can quote it and the matching
stack trace can be found in the logs -- and it must not leak the exception text
outside local/CI, since exception messages are where connection strings tend to
end up.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import (
    routes_auth,
    routes_documents,
    routes_eval,
    routes_extraction,
    routes_search,
    routes_system,
)
from app.config import settings
from app.db import engine, init_db
from app.observability.tracing import setup_tracing

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DESCRIPTION = """\
Turns clinical papers into structured, source-grounded evidence reviews.

Every extracted field carries a verbatim quote that is matched back against the
source document; anything that cannot be matched, or that falls below the
calibrated confidence threshold, is withheld and reported as an abstention
rather than guessed.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_production_safety()
    init_db()
    setup_tracing(app=app, engine=engine)
    logger.info(
        "%s v%s ready | db=%s | llm=%s | embeddings=%s",
        settings.app_name,
        __version__,
        "postgres" if settings.is_postgres else "sqlite",
        settings.resolved_llm_provider,
        settings.embedding_provider,
    )
    yield
    logger.info("Shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # we use bearer tokens, not cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error [%s] %s %s", request_id, request.method, request.url.path)
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Request validation failed.",
                "errors": exc.errors(),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        detail = (
            f"{type(exc).__name__}: {exc}"
            if settings.environment in ("local", "ci")
            else "Internal server error."
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": detail, "request_id": request_id},
        )

    prefix = settings.api_prefix
    app.include_router(routes_system.router, prefix=prefix)
    app.include_router(routes_auth.router, prefix=prefix)
    app.include_router(routes_documents.router, prefix=prefix)
    app.include_router(routes_search.router, prefix=prefix)
    app.include_router(routes_extraction.router, prefix=prefix)
    app.include_router(routes_eval.router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": f"{prefix}/health",
        }

    return app


app = create_app()
