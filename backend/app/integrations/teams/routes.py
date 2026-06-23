from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.integrations.teams.auth import teams_auth_configured, validate_activity_request
from app.integrations.teams.handlers import handle_activity
from app.integrations.teams.notifications import list_conversation_references, send_notification
from app.integrations.teams.schemas import TeamsActivity, TeamsNotificationRequest

router = APIRouter()
logger = logging.getLogger("finops.teams.routes")


@router.post("/messages")
async def teams_messages(request: Request):
    auth = await validate_activity_request(request)
    payload = await request.json()
    activity = TeamsActivity.model_validate(payload)
    logger.info("Teams message endpoint accepted activity type=%s auth=%s", activity.type, auth.get("mode") or auth.get("validated"))
    return await handle_activity(activity)


@router.get("/health")
async def teams_health():
    refs = list_conversation_references()
    return {
        "status": "ok",
        "bot_auth_configured": teams_auth_configured(),
        "conversation_references": len(refs),
        "endpoint": "/api/v1/teams/messages",
    }


@router.get("/conversations")
async def teams_conversations():
    return {"items": list_conversation_references()}


@router.post("/notify")
async def teams_notify(body: TeamsNotificationRequest):
    return await send_notification(
        title=body.title,
        text=body.text,
        severity=body.severity,
        conversation_id=body.conversation_id,
        service_url=body.service_url,
        card=body.card,
    )
