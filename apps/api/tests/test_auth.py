"""Authentication: Clerk JWTs are verified cryptographically and the API fails closed without JWKS."""

from __future__ import annotations

import base64
import logging
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.config import clerk_frontend_api_host, settings
from app.main import app

JWKS_URL = "https://clerk.example.dev/.well-known/jwks.json"
HS256_SECRET = "attacker-controlled-secret-with-enough-length"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubKey:
    def __init__(self, key):
        self.key = key


class _StubJWKSClient:
    """Mimics PyJWKClient: returns the signing key for any well-formed token."""

    def __init__(self, public_key):
        self._key = _StubKey(public_key)

    def get_signing_key_from_jwt(self, token: str):
        jwt.get_unverified_header(token)  # raises DecodeError for garbage, like the real client
        return self._key


def _token(private_key, **claims) -> str:
    payload = {"sub": "user_123", "exp": int(time.time()) + 300}
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, private_key, algorithm="RS256")


async def _authenticate(authorization=None, x_user_id=None) -> str:
    return await auth.get_current_user_id(x_user_id=x_user_id, authorization=authorization)


@pytest.fixture
def jwks(monkeypatch, signing_key):
    """JWKS verification configured and backed by the test key pair (production mode)."""
    monkeypatch.setattr(settings, "clerk_jwks_url", JWKS_URL)
    monkeypatch.setattr(settings, "clerk_issuer", "")
    monkeypatch.setattr(settings, "allow_dev_auth_header", False)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _StubJWKSClient(signing_key.public_key()))


@pytest.fixture
def no_jwks(monkeypatch):
    """No JWKS URL configured or derivable."""
    monkeypatch.setattr(settings, "clerk_jwks_url", "")
    monkeypatch.setattr(settings, "clerk_publishable_key", "")
    monkeypatch.setattr(settings, "allow_dev_auth_header", False)
    monkeypatch.setattr(settings, "app_env", "development")


class TestJwtVerification:
    async def test_valid_token_returns_subject(self, jwks, signing_key):
        assert await _authenticate(f"Bearer {_token(signing_key)}") == "user_123"

    async def test_expired_token_rejected(self, jwks, signing_key):
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {_token(signing_key, exp=int(time.time()) - 3600)}")
        assert exc.value.status_code == 401

    async def test_token_signed_by_another_key_rejected(self, jwks):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {_token(other)}")
        assert exc.value.status_code == 401

    async def test_hs256_token_rejected(self, jwks):
        forged = jwt.encode({"sub": "victim", "exp": int(time.time()) + 300}, HS256_SECRET, algorithm="HS256")
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {forged}")
        assert exc.value.status_code == 401

    async def test_unsigned_token_rejected(self, jwks):
        forged = jwt.encode({"sub": "victim", "exp": int(time.time()) + 300}, None, algorithm="none")
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {forged}")
        assert exc.value.status_code == 401

    async def test_token_without_subject_rejected(self, jwks, signing_key):
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {_token(signing_key, sub=None)}")
        assert exc.value.status_code == 401

    async def test_token_without_expiry_rejected(self, jwks, signing_key):
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {_token(signing_key, exp=None)}")
        assert exc.value.status_code == 401

    async def test_garbage_token_rejected(self, jwks):
        with pytest.raises(HTTPException) as exc:
            await _authenticate("Bearer not-a-jwt")
        assert exc.value.status_code == 401

    async def test_missing_bearer_rejected_even_with_user_id_header(self, jwks):
        with pytest.raises(HTTPException) as exc:
            await _authenticate(None, "user_victim")
        assert exc.value.status_code == 401

    async def test_non_bearer_scheme_rejected(self, jwks, signing_key):
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Basic {_token(signing_key)}")
        assert exc.value.status_code == 401

    async def test_issuer_enforced_when_configured(self, jwks, signing_key, monkeypatch):
        monkeypatch.setattr(settings, "clerk_issuer", "https://clerk.example.dev/")
        assert await _authenticate(f"Bearer {_token(signing_key, iss='https://clerk.example.dev')}") == "user_123"
        for bad in (_token(signing_key, iss="https://evil.example"), _token(signing_key)):
            with pytest.raises(HTTPException) as exc:
                await _authenticate(f"Bearer {bad}")
            assert exc.value.status_code == 401


class TestFailClosed:
    async def test_forged_jwt_not_trusted_without_jwks(self, no_jwks, monkeypatch):
        monkeypatch.setattr(settings, "clerk_secret_key", "sk_test_dummy")
        monkeypatch.setattr(settings, "app_env", "production")
        forged = jwt.encode({"sub": "victim"}, HS256_SECRET, algorithm="HS256")
        with pytest.raises(HTTPException) as exc:
            await _authenticate(f"Bearer {forged}", "victim")
        assert exc.value.status_code == 503

    async def test_x_user_id_not_trusted_by_default(self, no_jwks):
        with pytest.raises(HTTPException) as exc:
            await _authenticate(None, "user_victim")
        assert exc.value.status_code == 503

    async def test_dev_header_needs_explicit_opt_in(self, no_jwks, monkeypatch):
        monkeypatch.setattr(settings, "allow_dev_auth_header", True)
        assert await _authenticate(None, " user_dev ") == "user_dev"
        with pytest.raises(HTTPException) as exc:
            await _authenticate(None, None)
        assert exc.value.status_code == 401

    async def test_dev_header_never_honoured_in_production(self, no_jwks, monkeypatch):
        monkeypatch.setattr(settings, "allow_dev_auth_header", True)
        monkeypatch.setattr(settings, "app_env", "production")
        with pytest.raises(HTTPException) as exc:
            await _authenticate(None, "user_victim")
        assert exc.value.status_code == 503

    async def test_dev_header_ignored_when_jwks_configured(self, jwks, monkeypatch):
        monkeypatch.setattr(settings, "allow_dev_auth_header", True)
        monkeypatch.setattr(settings, "app_env", "development")
        with pytest.raises(HTTPException) as exc:
            await _authenticate(None, "user_victim")
        assert exc.value.status_code == 401

    def test_startup_logs_error_when_unconfigured(self, no_jwks, caplog):
        with caplog.at_level(logging.ERROR, logger="app.auth"):
            auth.log_auth_configuration()
        assert "No Clerk JWKS URL configured" in caplog.text


class TestJwksUrlResolution:
    @staticmethod
    def _publishable_key(host: str) -> str:
        return "pk_test_" + base64.b64encode(f"{host}$".encode()).decode().rstrip("=")

    def test_frontend_api_host_decoded_from_publishable_key(self):
        assert clerk_frontend_api_host(self._publishable_key("clerk.example.accounts.dev")) == "clerk.example.accounts.dev"

    @pytest.mark.parametrize("value", ["", "garbage", "pk_test_", "sk_test_abc", "pk_test_!!!"])
    def test_invalid_publishable_key_yields_no_host(self, value):
        assert clerk_frontend_api_host(value) is None

    def test_explicit_jwks_url_wins(self, monkeypatch):
        monkeypatch.setattr(settings, "clerk_jwks_url", JWKS_URL)
        monkeypatch.setattr(settings, "clerk_publishable_key", self._publishable_key("other.example.dev"))
        assert settings.effective_clerk_jwks_url == JWKS_URL

    def test_jwks_url_derived_from_publishable_key(self, monkeypatch):
        monkeypatch.setattr(settings, "clerk_jwks_url", "")
        monkeypatch.setattr(settings, "clerk_publishable_key", self._publishable_key("clerk.example.accounts.dev"))
        assert settings.effective_clerk_jwks_url == "https://clerk.example.accounts.dev/.well-known/jwks.json"


class TestHttpLayer:
    def test_protected_route_returns_503_when_auth_unconfigured(self, no_jwks):
        response = TestClient(app).get("/routes", headers={"Authorization": "Bearer forged", "X-User-Id": "victim"})
        assert response.status_code == 503

    def test_protected_route_rejects_forged_token_when_configured(self, jwks):
        response = TestClient(app).get("/routes", headers={"Authorization": "Bearer abc.def.ghi"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
