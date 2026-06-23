from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException, Request

from config import settings

logger = logging.getLogger("finops.teams.auth")

_OPENID_CONFIG_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
_JWKS_CACHE: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=timezone.utc), "keys": None}
_CONNECTOR_TOKEN: dict[str, Any] = {"expires_at": datetime.min.replace(tzinfo=timezone.utc), "token": ""}


def teams_auth_configured() -> bool:
    return bool(settings.BOT_APP_ID and settings.BOT_APP_SECRET)


async def validate_activity_request(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("authorization", "")
    if not settings.BOT_VALIDATE_AUTH:
        return {"validated": False, "mode": "disabled"}

    if not auth_header:
        if settings.BOT_ALLOW_INSECURE_LOCAL and settings.ENVIRONMENT.lower() in {"dev", "development", "local"}:
            logger.warning("Teams request accepted without Authorization because BOT_ALLOW_INSECURE_LOCAL is enabled.")
            return {"validated": False, "mode": "local-insecure"}
        raise HTTPException(status_code=401, detail="Missing Bot Framework Authorization header")

    if not teams_auth_configured():
        raise HTTPException(status_code=500, detail="BOT_APP_ID and BOT_APP_SECRET must be configured")

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Bot Framework Authorization header")

    try:
        try:
            from jose import JWTError, jwt
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="python-jose is required for Bot Framework token validation") from exc

        keys = await _get_botframework_jwks()
        claims = jwt.decode(
            token,
            keys,
            algorithms=["RS256"],
            audience=settings.BOT_APP_ID,
            options={"verify_iss": False},
        )
        _validate_issuer(claims)
        return {"validated": True, "app_id": claims.get("aud"), "issuer": claims.get("iss")}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Teams token validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Bot Framework token") from exc


async def get_connector_token() -> str:
    if not teams_auth_configured():
        raise RuntimeError("BOT_APP_ID and BOT_APP_SECRET are required for Teams replies")

    now = datetime.now(timezone.utc)
    if _CONNECTOR_TOKEN["token"] and _CONNECTOR_TOKEN["expires_at"] > now + timedelta(minutes=5):
        return _CONNECTOR_TOKEN["token"]

    token_url = f"https://login.microsoftonline.com/{settings.BOT_AUTH_TENANT or 'botframework.com'}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.BOT_APP_ID,
        "client_secret": settings.BOT_APP_SECRET,
        "scope": "https://api.botframework.com/.default",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(token_url, data=data)
        response.raise_for_status()
        payload = response.json()

    _CONNECTOR_TOKEN["token"] = payload["access_token"]
    _CONNECTOR_TOKEN["expires_at"] = now + timedelta(seconds=int(payload.get("expires_in", 3600)))
    return _CONNECTOR_TOKEN["token"]


async def _get_botframework_jwks() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    if _JWKS_CACHE["keys"] and _JWKS_CACHE["expires_at"] > now:
        return _JWKS_CACHE["keys"]

    async with httpx.AsyncClient(timeout=15) as client:
        config_response = await client.get(_OPENID_CONFIG_URL)
        config_response.raise_for_status()
        jwks_uri = config_response.json()["jwks_uri"]
        jwks_response = await client.get(jwks_uri)
        jwks_response.raise_for_status()
        keys = jwks_response.json()

    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["expires_at"] = now + timedelta(hours=12)
    return keys


def _validate_issuer(claims: dict[str, Any]) -> None:
    issuer = str(claims.get("iss", "")).rstrip("/")
    tenant = (settings.BOT_TENANT_ID or "").strip()
    allowed = {
        "https://api.botframework.com",
        "https://sts.windows.net/d6d49420-f39b-4df7-a1dc-d59a935871db",
    }
    if tenant:
        allowed.add(f"https://sts.windows.net/{tenant}")
        allowed.add(f"https://login.microsoftonline.com/{tenant}/v2.0")
    if issuer and issuer not in allowed:
        raise ValueError(f"Unexpected token issuer: {issuer}")
