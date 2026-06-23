"""
integrations/teams/bot_client.py
Microsoft Teams webhook notifications.

Sends Adaptive Card alerts to a Teams channel.
Requires TEAMS_WEBHOOK_URL in .env.

Architecture role: called by Alert Agent and routers/alerts.py.
"""

from __future__ import annotations
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger("finops.teams")


_SEVERITY_COLORS = {
    "critical": "attention",   # Red in Adaptive Cards
    "warning":  "warning",     # Yellow
    "info":     "accent",      # Blue
    "resolved": "good",        # Green
}


def _build_card(
    title: str,
    severity: str,
    resource: str,
    detail: str,
    action_url: Optional[str] = None,
) -> dict:
    """Build a Teams Adaptive Card payload."""
    color = _SEVERITY_COLORS.get(severity.lower(), "default")

    card: dict = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type":    "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type":   "TextBlock",
                            "text":   f"🔔 FinOps.AI Alert — {severity.upper()}",
                            "weight": "Bolder",
                            "size":   "Medium",
                            "color":  color,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Alert",    "value": title},
                                {"title": "Resource", "value": resource},
                                {"title": "Detail",   "value": detail},
                                {"title": "Severity", "value": severity.capitalize()},
                            ],
                        },
                    ],
                    **(
                        {
                            "actions": [
                                {
                                    "type":  "Action.OpenUrl",
                                    "title": "View in FinOps Dashboard",
                                    "url":   action_url,
                                }
                            ]
                        }
                        if action_url
                        else {}
                    ),
                },
            }
        ],
    }
    return card


async def send_teams_card(
    title: str,
    severity: str,
    resource: str,
    detail: str,
    action_url: Optional[str] = None,
) -> dict:
    """
    POST an Adaptive Card to the configured Teams webhook.

    Returns {"status": "sent"} on success.
    Raises RuntimeError if TEAMS_WEBHOOK_URL is not configured.
    Raises httpx.HTTPStatusError on delivery failure.
    """
    webhook_url = settings.TEAMS_WEBHOOK_URL
    if not webhook_url:
        raise RuntimeError(
            "TEAMS_WEBHOOK_URL is not configured. "
            "Add it to .env to enable Teams notifications."
        )

    card = _build_card(title, severity, resource, detail, action_url)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = client.post(webhook_url, json=card)
        resp.raise_for_status()

    logger.info("Teams card sent: [%s] %s", severity.upper(), title)
    return {"status": "sent", "channel": "teams", "title": title}
