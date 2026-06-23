"""
agents/alert_agent.py — Alert Agent.
Formats and dispatches alerts via Teams, Email, and Twilio Voice.

Architecture Layer: Agent Layer → Alert Agent
Triggered by:
  • AnomalyAgent  (cost/resource spikes)
  • IncidentAgent (P1/P2 fires)
  • ForecastAgent (budget breach prediction)
  • GovernanceAgent (policy violation)

Channels:
  • Microsoft Teams  — Adaptive Card webhook (FREE)
  • Email            — Azure Communication Services or SMTP
  • Twilio Voice     — Phone call for P1 incidents (paid, tiny cost)

Phase 5 full implementation. Currently graceful stubs that log the alert
and return success — no external calls until webhook URL is configured.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from agents.base_agent import BaseAgent
from config import settings

logger = logging.getLogger("finops.alert")

# ── Severity → Teams card colour ──────────────────────────────────────────────
_CARD_COLOURS = {
    "critical": "attention",   # red
    "warning":  "warning",     # orange/yellow
    "info":     "accent",      # blue
    "resolved": "good",        # green
}


class AlertAgent(BaseAgent):
    name        = "Alert Agent"
    description = "Multi-channel alert dispatch: Teams, Email, Twilio Voice"

    system_prompt = """
You are FinOps.AI's Alert Agent. You format cloud cost and health alerts
for human consumption across multiple channels (Teams, email, voice).

Your responsibilities:
- Write clear, concise alert messages tailored to the channel.
- Include: what happened, which resource, severity, recommended action.
- For Teams: use Adaptive Card format with Approve / Investigate buttons.
- For email: brief subject + structured body.
- For voice: short, punchy 15-second script (Twilio TTS).

Tone: direct, factual, urgent-but-not-panicky. Ops teams hate noise.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch an alert to all configured channels.

        Payload keys:
          title    (str)   Alert title
          severity (str)   critical / warning / info / resolved
          resource (str)   Affected resource name
          detail   (str)   Description of what happened
          delta    (str)   e.g. "+$180/day" or "+340%"
          action_url (str) Optional URL for "Investigate" button
        """
        title    = payload.get("title",    "FinOps.AI Alert")
        severity = payload.get("severity", "warning")
        resource = payload.get("resource", "unknown")
        detail   = payload.get("detail",   "")
        delta    = payload.get("delta",    "")

        dispatched = []

        # ── Teams ──────────────────────────────────────────────────────────────
        teams_url = getattr(settings, "TEAMS_WEBHOOK_URL", "")
        if teams_url:
            ok = await self._send_teams(title, severity, resource, detail, delta, teams_url)
            if ok:
                dispatched.append("teams")
        else:
            logger.info(f"[AlertAgent] Teams: no webhook configured — logged only")
            logger.info(f"  [{severity.upper()}] {title} | {resource} | {delta}")

        # ── Email ──────────────────────────────────────────────────────────────
        # Phase 5: wire Azure Communication Services or SMTP here
        # await self._send_email(title, severity, resource, detail)

        # ── Twilio Voice (P1 only) ─────────────────────────────────────────────
        if severity == "critical":
            twilio_phone = getattr(settings, "VOICE_ALERT_PHONE", "")
            if twilio_phone:
                ok = await self._send_voice(title, resource, delta, twilio_phone)
                if ok:
                    dispatched.append("voice")

        return {
            "response":   f"Alert dispatched via: {', '.join(dispatched) or 'log only'}",
            "actions":    [],
            "dispatched": dispatched,
            "logged_at":  datetime.now(timezone.utc).isoformat(),
        }

    # ── Teams Adaptive Card ────────────────────────────────────────────────────

    async def _send_teams(
        self,
        title: str,
        severity: str,
        resource: str,
        detail: str,
        delta: str,
        webhook_url: str,
    ) -> bool:
        """Send an Adaptive Card to a Teams channel via incoming webhook."""
        try:
            import httpx

            colour = _CARD_COLOURS.get(severity, "accent")
            card = {
                "type": "message",
                "attachments": [{
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": f"🚨 {title}" if severity == "critical" else f"⚠️ {title}",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": colour,
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Resource",  "value": resource},
                                    {"title": "Severity",  "value": severity.upper()},
                                    {"title": "Impact",    "value": delta or "—"},
                                    {"title": "Detail",    "value": detail or "—"},
                                    {"title": "Detected",  "value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")},
                                ],
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "🔍 Investigate",
                                "url":   "http://localhost:5173/anomaly",
                            },
                            {
                                "type": "Action.OpenUrl",
                                "title": "✅ Open Approvals",
                                "url":   "http://localhost:5173/approvals",
                            },
                        ],
                    },
                }],
            }

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook_url, json=card)
                resp.raise_for_status()

            logger.info(f"[AlertAgent] Teams card sent: {title}")
            return True

        except ImportError:
            logger.warning("httpx not installed. Run: pip install httpx --break-system-packages")
            return False
        except Exception as exc:
            logger.error(f"[AlertAgent] Teams send failed: {exc}")
            return False

    # ── Twilio Voice ───────────────────────────────────────────────────────────

    async def _send_voice(
        self,
        title: str,
        resource: str,
        delta: str,
        to_phone: str,
    ) -> bool:
        """
        Place a Twilio voice call with a TTS alert script.
        Phase 5: requires TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_PHONE in .env
        """
        try:
            from twilio.rest import Client as TwilioClient

            account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
            auth_token  = getattr(settings, "TWILIO_AUTH_TOKEN",  "")
            from_phone  = getattr(settings, "TWILIO_FROM_PHONE",  "")

            if not all([account_sid, auth_token, from_phone]):
                logger.info("[AlertAgent] Twilio not configured — skipping voice call")
                return False

            script = (
                f"This is FinOps dot A I. "
                f"Critical alert on {resource}. "
                f"{title}. "
                f"Impact: {delta}. "
                f"Please review the dashboard immediately."
            )

            client = TwilioClient(account_sid, auth_token)
            call   = client.calls.create(
                twiml=f"<Response><Say>{script}</Say><Pause length='1'/><Say>Repeating. {script}</Say></Response>",
                to=to_phone,
                from_=from_phone,
            )

            logger.info(f"[AlertAgent] Twilio voice call placed: SID={call.sid}")
            return True

        except ImportError:
            logger.info("[AlertAgent] Twilio SDK not installed — skipping voice call")
            return False
        except Exception as exc:
            logger.error(f"[AlertAgent] Twilio call failed: {exc}")
            return False

    # ── Email ──────────────────────────────────────────────────────────────────

    async def _send_email(
        self,
        title: str,
        severity: str,
        resource: str,
        detail: str,
        to_email: str,
    ) -> bool:
        """
        Send alert email via Azure Communication Services.
        Phase 5: set AZURE_COMMUNICATION_CONNECTION_STRING in .env
        """
        try:
            conn_str = getattr(settings, "AZURE_COMMUNICATION_CONNECTION_STRING", "")
            if not conn_str:
                logger.info("[AlertAgent] Azure Communication Services not configured")
                return False

            from azure.communication.email import EmailClient

            client = EmailClient.from_connection_string(conn_str)
            message = {
                "senderAddress": "noreply@finops-ai.azurecomm.net",
                "recipients": {"to": [{"address": to_email}]},
                "content": {
                    "subject": f"[FinOps.AI {severity.upper()}] {title}",
                    "plainText": (
                        f"Alert: {title}\n"
                        f"Severity: {severity.upper()}\n"
                        f"Resource: {resource}\n"
                        f"Detail: {detail}\n\n"
                        f"View dashboard: http://localhost:5173"
                    ),
                },
            }
            client.begin_send(message)
            logger.info(f"[AlertAgent] Email sent to {to_email}")
            return True

        except ImportError:
            logger.info("[AlertAgent] Azure Communication SDK not installed")
            return False
        except Exception as exc:
            logger.error(f"[AlertAgent] Email failed: {exc}")
            return False


# ── Module-level helper used by other agents ──────────────────────────────────

_alert_agent_instance: Optional[AlertAgent] = None


def get_alert_agent() -> AlertAgent:
    global _alert_agent_instance
    if _alert_agent_instance is None:
        _alert_agent_instance = AlertAgent()
    return _alert_agent_instance


async def dispatch_alert(
    title: str,
    severity: str,
    resource: str,
    detail: str = "",
    delta: str  = "",
) -> Dict[str, Any]:
    """
    Convenience function — other agents call this to send alerts.

    Example:
        from agents.alert_agent import dispatch_alert
        await dispatch_alert(
            title="Budget breach predicted",
            severity="critical",
            resource="subscription/prod",
            detail="Forecast $27,340 vs $25,000 budget",
            delta="+$2,340",
        )
    """
    agent = get_alert_agent()
    return await agent.run({
        "title":    title,
        "severity": severity,
        "resource": resource,
        "detail":   detail,
        "delta":    delta,
    })
