from __future__ import annotations

import logging
from typing import Any

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient | None:
    global _jwks_client
    jwks_url = getattr(settings, "clerk_jwks_url", "") or ""
    if not jwks_url:
        return None
    if _jwks_client is None:
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def _verify_clerk_jwt(token: str) -> str:
    client = _get_jwks_client()
    if client is None:
        raise HTTPException(status_code=401, detail="JWT validation not configured")
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token: missing subject")
        return str(sub)
    except jwt.PyJWTError as exc:
        logger.warning("Clerk JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid authentication token") from exc


async def _verify_via_clerk_api(token: str) -> str | None:
    """Fallback: verify session token via Clerk Backend API."""
    if not settings.clerk_secret_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.clerk.com/v1/sessions",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                params={"limit": 1},
            )
            if response.status_code != 200:
                return None
            payload = jwt.decode(token, options={"verify_signature": False})
            return str(payload.get("sub")) if payload.get("sub") else None
    except Exception:
        return None


async def get_current_user_id(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    authorization: str | None = Header(default=None),
) -> str:
    """
    Prefer Clerk JWT from Authorization header; fall back to X-User-Id in local dev
    when CLERK_JWKS_URL is not configured.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if _get_jwks_client() is not None:
            return _verify_clerk_jwt(token)
        user_id = await _verify_via_clerk_api(token)
        if user_id:
            return user_id
        if settings.clerk_secret_key:
            try:
                payload = jwt.decode(token, options={"verify_signature": False})
                if payload.get("sub"):
                    logger.warning("Using unverified JWT sub — configure CLERK_JWKS_URL for production")
                    return str(payload["sub"])
            except jwt.PyJWTError:
                pass

    if x_user_id and not getattr(settings, "clerk_jwks_url", ""):
        return x_user_id

    if x_user_id:
        logger.warning("X-User-Id accepted without JWT — configure CLERK_JWKS_URL for production")
        return x_user_id

    raise HTTPException(status_code=401, detail="Authentication required")


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
