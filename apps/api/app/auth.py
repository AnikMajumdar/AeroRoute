from __future__ import annotations

import logging
from typing import Any

import jwt
from fastapi import Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger(__name__)

_UNAUTHENTICATED_HEADERS = {"WWW-Authenticate": "Bearer"}

_jwks_client: PyJWKClient | None = None
_jwks_client_url: str | None = None


def _get_jwks_client() -> PyJWKClient | None:
    """Cached Clerk JWKS client, or None when no JWKS URL is configured or derivable."""
    global _jwks_client, _jwks_client_url
    jwks_url = settings.effective_clerk_jwks_url
    if not jwks_url:
        return None
    if _jwks_client is None or _jwks_client_url != jwks_url:
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=5)
        _jwks_client_url = jwks_url
    return _jwks_client


def _verify_clerk_jwt(token: str, client: PyJWKClient) -> str:
    """Verify a Clerk session token (RS256 signature, exp, sub and, when configured, issuer) and return its subject."""
    issuer = settings.clerk_issuer.strip().rstrip("/")
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer or None,
            leeway=10,
            # Clerk session tokens carry no audience claim.
            options={"require": ["exp", "sub"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        logger.warning("Clerk JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=401, detail="Invalid authentication token", headers=_UNAUTHENTICATED_HEADERS
        ) from exc
    return str(payload["sub"])


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def dev_header_auth_enabled() -> bool:
    """X-User-Id is a local-development shortcut: explicit opt-in and never in production."""
    return bool(settings.allow_dev_auth_header) and not settings.is_production


def log_auth_configuration() -> None:
    """Log how requests are authenticated; called once at startup."""
    if settings.effective_clerk_jwks_url:
        if settings.allow_dev_auth_header:
            logger.warning("ALLOW_DEV_AUTH_HEADER is ignored because a Clerk JWKS URL is configured")
        return
    if dev_header_auth_enabled():
        logger.warning("No Clerk JWKS URL configured: trusting the X-User-Id header (local development only)")
    else:
        logger.error(
            "No Clerk JWKS URL configured: authenticated endpoints return 503. "
            "Set CLERK_JWKS_URL (or CLERK_PUBLISHABLE_KEY), or ALLOW_DEV_AUTH_HEADER=true for local development."
        )


async def get_current_user_id(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    authorization: str | None = Header(default=None),
) -> str:
    """
    Authenticate the caller and return the Clerk user id.

    A Clerk JWKS URL (explicit, or derived from the publishable key) is required: the bearer token is then
    verified cryptographically. Without it the API fails closed (503); the only exception is the explicit
    local-development opt-in ALLOW_DEV_AUTH_HEADER, which trusts X-User-Id outside production.
    """
    client = _get_jwks_client()
    if client is not None:
        token = _extract_bearer_token(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="Authentication required", headers=_UNAUTHENTICATED_HEADERS)
        return await run_in_threadpool(_verify_clerk_jwt, token, client)

    if dev_header_auth_enabled():
        user_id = (x_user_id or "").strip()
        if user_id:
            return user_id
        raise HTTPException(status_code=401, detail="Authentication required", headers=_UNAUTHENTICATED_HEADERS)

    raise HTTPException(status_code=503, detail="Authentication is not configured")


def row_to_airport(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ident": row.get("ident", ""),
        "icao_code": row.get("icao_code"),
        "iata_code": row.get("iata_code"),
        "name": row.get("name") or row.get("ident", "Unknown Airport"),
        "municipality": row.get("municipality"),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "airport_type": row.get("airport_type", "small_airport"),
        "longest_runway_ft": row.get("longest_runway_ft"),
    }
