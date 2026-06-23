from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.teams.auth import get_connector_token
from app.integrations.teams.schemas import TeamsActivity

logger = logging.getLogger("finops.teams.adapter")


async def send_activity(
    source_activity: TeamsActivity,
    text: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not source_activity.service_url or not source_activity.conversation.id:
        logger.warning("Cannot send Teams reply because serviceUrl or conversation id is missing.")
        return {"sent": False, "reason": "missing_conversation_reference"}

    return await send_to_conversation(
        service_url=source_activity.service_url,
        conversation_id=source_activity.conversation.id,
        text=text,
        attachments=attachments or [],
        reply_to_id=source_activity.id,
    )


async def send_to_conversation(
    service_url: str,
    conversation_id: str,
    text: str = "",
    attachments: list[dict[str, Any]] | None = None,
    reply_to_id: str = "",
) -> dict[str, Any]:
    try:
        token = await get_connector_token()
        base = service_url.rstrip("/")
        if reply_to_id:
            url = f"{base}/v3/conversations/{conversation_id}/activities/{reply_to_id}"
        else:
            url = f"{base}/v3/conversations/{conversation_id}/activities"
        payload = {
            "type": "message",
            "text": text,
            "attachments": attachments or [],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload)
            response.raise_for_status()
            data = response.json() if response.content else {}
        logger.info("Teams activity sent to conversation=%s reply=%s", conversation_id, bool(reply_to_id))
        return {"sent": True, "result": data}
    except Exception as exc:
        logger.error("Teams activity send failed: %s: %s", type(exc).__name__, exc)
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
