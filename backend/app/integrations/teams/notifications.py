from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from app.integrations.teams.adapter import send_to_conversation
from app.integrations.teams.cards import text_attachment
from app.integrations.teams.schemas import TeamsActivity

logger = logging.getLogger("finops.teams.notifications")
_STATE_PATH = Path(settings.FINOPS_STATE_FILE)


def save_conversation_reference(activity: TeamsActivity) -> None:
    if not activity.service_url or not activity.conversation.id:
        return
    data = _read_state()
    refs = data.setdefault("teams_conversations", {})
    refs[activity.conversation.id] = {
        "service_url": activity.service_url,
        "conversation_id": activity.conversation.id,
        "conversation_type": activity.conversation.conversation_type,
        "channel_id": activity.channel_id,
        "tenant_id": _tenant_id(activity),
        "user_id": activity.from_property.id,
        "user_name": activity.from_property.name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_state(data)


def list_conversation_references() -> list[dict[str, Any]]:
    return list((_read_state().get("teams_conversations") or {}).values())


async def send_notification(
    title: str,
    text: str,
    severity: str = "info",
    conversation_id: str = "",
    service_url: str = "",
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = _resolve_target(conversation_id, service_url)
    if not target:
        return {"sent": False, "reason": "No Teams conversation reference is available yet. Send the bot a message first."}
    attachment = card or text_attachment(title, text, severity)
    result = await send_to_conversation(
        service_url=target["service_url"],
        conversation_id=target["conversation_id"],
        text="",
        attachments=[attachment],
    )
    logger.info("Teams notification sent: %s", title)
    return {"sent": True, "target": target["conversation_id"], "result": result}


def _resolve_target(conversation_id: str, service_url: str) -> dict[str, Any] | None:
    if conversation_id and service_url:
        return {"conversation_id": conversation_id, "service_url": service_url}
    if settings.TEAMS_DEFAULT_CONVERSATION_ID and settings.TEAMS_DEFAULT_SERVICE_URL:
        return {"conversation_id": settings.TEAMS_DEFAULT_CONVERSATION_ID, "service_url": settings.TEAMS_DEFAULT_SERVICE_URL}
    refs = list_conversation_references()
    return refs[-1] if refs else None


def _tenant_id(activity: TeamsActivity) -> str:
    channel_data = activity.channel_data if isinstance(activity.channel_data, dict) else activity.channel_data.model_dump()
    tenant = channel_data.get("tenant") or {}
    return str(tenant.get("id") or activity.conversation.tenant_id or "")


def _read_state() -> dict[str, Any]:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read Teams state: %s", exc)
    return {}


def _write_state(data: dict[str, Any]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist Teams state: %s", exc)
