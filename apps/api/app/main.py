import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from postgrest.exceptions import APIError

from app.auth import log_auth_configuration
from app.config import settings
from app.logging_config import configure_logging
from app.routers.routes import router

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AeroRoute API",
    description="Educational flight route optimization API",
    version="0.1.0",
)


def cors_options() -> dict[str, Any]:
    """CORS policy: exact origins from API_CORS_ORIGINS (plus an optional, project-specific regex)."""
    return {
        "allow_origins": settings.cors_origins,
        "allow_origin_regex": settings.api_cors_origin_regex or None,
        # Authentication uses the Authorization header, never cookies, so credentialed requests are not needed.
        "allow_credentials": False,
        "allow_methods": ["GET", "POST", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "X-User-Id"],
    }


app.add_middleware(CORSMiddleware, **cors_options())

app.include_router(router)


@app.exception_handler(APIError)
async def database_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Unexpected PostgREST errors become a clean JSON 500; details stay in the logs."""
    logger.error("Database error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Database error"})


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send browsers to interactive API docs."""
    return RedirectResponse(url="/docs")


@app.on_event("startup")
async def startup() -> None:
    logger.info("AeroRoute API starting up")
    log_auth_configuration()
