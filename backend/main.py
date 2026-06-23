"""
main.py — FastAPI application entry point.
All routers, CORS, lifespan, and health check.
"""

import logging
import os
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger("finops.ai")


def _cors_origins() -> list[str]:
    if _cors_allow_all():
        return ["*"]
    configured = _parse_cors_origins(settings.CORS_ORIGINS)
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]
    return sorted(set(configured + defaults))


def _cors_allow_all() -> bool:
    return "*" in set(_parse_cors_origins(settings.CORS_ORIGINS))


def _parse_cors_origins(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw.split(",")
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    return [
        str(origin).strip().strip('"').strip("'").rstrip("/")
        for origin in parsed
        if str(origin).strip()
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀  FinOps.AI Platform starting  |  env=%s", settings.ENVIRONMENT)
    logger.info("    Azure OpenAI deployment: %s", settings.AZURE_OPENAI_DEPLOYMENT or "NOT SET")
    logger.info("    Subscription: %s", settings.AZURE_SUBSCRIPTION_ID[:8] + "..." if settings.AZURE_SUBSCRIPTION_ID else "NOT SET")
    logger.info("    CORS origins: %s", ", ".join(_cors_origins()))
    print(f"FINOPS_CORS_ORIGINS={','.join(_cors_origins())}", flush=True)
    yield
    logger.info("FinOps.AI Platform shutting down")


app = FastAPI(
    title="FinOps AI Platform",
    version="2.0.0",
    description="Multi-agent Azure FinOps platform powered by LangGraph + GPT-4o",
    lifespan=lifespan,
)

# ── CORS (allow React dev server) ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=not _cors_allow_all(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from routers.cost import router as cost_router
from routers.cloudops import router as cloudops_router
from routers.anomalies import router as anomaly_router
from routers.approvals import router as approval_router
from routers.chat import router as chat_router
from routers.azure import router as azure_router
from routers.forecast import router as forecast_router
from routers.mcp_router_endpoint import router as mcp_router
from routers.security import router as security_router
from routers.guardrails import router as guardrails_router
from app.integrations.teams.routes import router as teams_router

app.include_router(azure_router,    prefix="/api/v1/azure",     tags=["Azure Connection"])
app.include_router(cost_router,     prefix="/api/v1/cost",      tags=["Cost"])
app.include_router(cloudops_router, prefix="/api/v1/cloudops",  tags=["CloudOps"])
app.include_router(anomaly_router,  prefix="/api/v1/anomalies", tags=["Anomalies"])
app.include_router(approval_router, prefix="/api/v1/approvals", tags=["Approvals"])
app.include_router(chat_router,     prefix="/api/v1/chat",      tags=["Chat / AI"])
app.include_router(forecast_router, prefix="/api/v1/forecast",  tags=["Forecast"])
app.include_router(mcp_router,      prefix="/api/v1/mcp",       tags=["MCP Tools"])
app.include_router(security_router, prefix="/api/v1/security",  tags=["Security"])
app.include_router(guardrails_router, prefix="/api/v1/guardrails", tags=["Guardrails"])
app.include_router(teams_router,    prefix="/api/v1/teams",     tags=["Microsoft Teams"])


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
        "azure_openai": bool(settings.AZURE_OPENAI_KEY),
        "azure_openai_endpoint_host": settings.AZURE_OPENAI_ENDPOINT.replace("https://", "").split("/")[0] if settings.AZURE_OPENAI_ENDPOINT else "",
        "azure_openai_endpoint_family": settings.openai_endpoint_family(),
        "azure_openai_v1_base_url": settings.openai_v1_base_url() if settings.AZURE_OPENAI_ENDPOINT else "",
        "azure_openai_deployment": settings.AZURE_OPENAI_DEPLOYMENT,
        "azure_openai_api_version": settings.AZURE_OPENAI_API_VERSION,
        "azure_subscription": bool(settings.AZURE_SUBSCRIPTION_ID),
        "build_version": os.getenv("FINOPS_BUILD_VERSION", "local"),
        "cors_origins_parsed": _cors_origins(),
    }


@app.get("/debug/cors")
async def debug_cors():
    return {
        "cors_origins_env": os.getenv("CORS_ORIGINS", ""),
        "cors_origins_settings": settings.CORS_ORIGINS,
        "cors_origins_parsed": _cors_origins(),
        "allow_credentials": not _cors_allow_all(),
        "environment": settings.ENVIRONMENT,
    }


@app.get("/debug/routes")
async def debug_routes():
    return {
        "build_version": os.getenv("FINOPS_BUILD_VERSION", "local"),
        "routes": sorted(route.path for route in app.routes),
    }


@app.get("/")
async def root():
    return {"message": "FinOps AI Platform v2.0 — /docs for API reference"}
