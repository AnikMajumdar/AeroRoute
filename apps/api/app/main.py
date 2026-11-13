import logging

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Vercel preview + production deployments (belt-and-suspenders if client calls Modal directly)
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
