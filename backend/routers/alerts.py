"""
routers/alerts.py — /api/v1/alerts/*

Endpoints:
  POST /test-call          → Trigger a test Twilio voice alert
  POST /teams              → Send a manual Teams notification
  GET  /history            → Recent alert history

Alert flow (architecture):
  Agent detects anomaly → Alert Agent → Teams + Email + Twilio Voice
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from models.schemas import Severity

router = APIRouter(tags=["Alerts"])
logger = logging.getLogger("finops.alerts")

# In-memory alert history (replace with Azure Table Storage in production)
_alert_history: list = []


class ManualAlertRequest(BaseModel):
    title: str
    severity: Severity
    resource: str
    detail: str
    channels: list[str] = ["teams"]  # teams | email | voice


class VoiceTestRequest(BaseModel):
    phone: Optional[str] = None     # Override default VOICE_ALERT_PHONE
    message: Optional[str] = None


@router.get("/history")
async def alert_history():
    """Recent alert dispatch history."""
    return {
        "total": len(_alert_history),
        "items": list(reversed(_alert_history))[:50],
    }


@router.post("/teams")
async def send_teams_alert(body: ManualAlertRequest):
    """
    Dispatch a Teams card notification.
    Requires TEAMS_WEBHOOK_URL in .env.
    """
    from integrations.teams.bot_client import send_teams_card
    try:
        result = await send_teams_card(
            title=body.title,
            severity=body.severity,
            resource=body.resource,
            detail=body.detail,
        )
        _record_history("teams", body.title, body.severity, result)
        return {"channel": "teams", "status": "sent", "detail": result}
    except Exception as exc:
        logger.error("Teams alert failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Teams delivery failed: {exc}")


@router.post("/test-call")
async def test_voice_call(body: VoiceTestRequest = VoiceTestRequest()):
    """
    Trigger a Twilio voice call alert.
    Requires TWILIO_* credentials and VOICE_ALERT_PHONE in .env.
    """
    from integrations.twilio.voice_client import make_alert_call
    from config import settings

    phone   = body.phone or settings.VOICE_ALERT_PHONE
    message = body.message or "This is a FinOps AI alert. An anomaly has been detected on your Azure subscription."

    if not phone:
        raise HTTPException(
            status_code=422,
            detail="No phone number configured. Set VOICE_ALERT_PHONE in .env or pass phone in request body.",
        )
    try:
        result = await make_alert_call(phone=phone, message=message)
        _record_history("voice", "Test call", Severity.INFO, result)
        return {"channel": "voice", "status": "initiated", "phone": phone, "detail": result}
    except Exception as exc:
        logger.error("Voice call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Voice call failed: {exc}")


def _record_history(channel: str, title: str, severity: Severity, result: dict):
    _alert_history.append({
        "channel":    channel,
        "title":      title,
        "severity":   severity,
        "result":     result,
        "sent_at":    datetime.now(timezone.utc).isoformat(),
    })
