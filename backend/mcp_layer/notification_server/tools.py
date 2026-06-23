"""
mcp/notification_server/tools.py — Notification MCP Server

Tools:
  send_teams_alert()     → Teams Adaptive Card via webhook
  send_email_alert()     → Email via Azure Communication Services
  trigger_voice_call()   → Twilio TTS voice call for P1 incidents

Used by: AlertAgent
"""

from mcp_layer.tool_registry import tool_registry


@tool_registry.register(
    name="send_teams_alert",
    server="notification",
    description="Send an Adaptive Card alert to Microsoft Teams via webhook",
    tags=["teams", "alert", "notification"],
)
async def send_teams_alert(
    title: str = "FinOps.AI Alert",
    severity: str = "warning",
    resource: str = "",
    detail: str = "",
    delta: str = "",
    **kwargs,
) -> dict:
    from agents.alert_agent import dispatch_alert
    result = await dispatch_alert(
        title=title, severity=severity,
        resource=resource, detail=detail, delta=delta,
    )
    return {
        "success":    "teams" in result.get("dispatched", []),
        "dispatched": result.get("dispatched", []),
        "logged_at":  result.get("logged_at"),
    }


@tool_registry.register(
    name="send_email_alert",
    server="notification",
    description="Send alert email via Azure Communication Services",
    tags=["email", "alert", "notification"],
)
async def send_email_alert(
    to_email: str = "",
    title: str = "",
    body: str = "",
    severity: str = "warning",
    **kwargs,
) -> dict:
    if not to_email:
        return {"success": False, "error": "to_email is required"}
    return {
        "success":   False,
        "channel":   "email",
        "data_source": "empty",
        "note":      "Phase 5: Set AZURE_COMMUNICATION_CONNECTION_STRING in .env",
    }


@tool_registry.register(
    name="trigger_voice_call",
    server="notification",
    description="Place a Twilio TTS voice call for P1/critical incidents",
    tags=["twilio", "voice", "p1", "alert"],
)
async def trigger_voice_call(
    phone_number: str = "",
    message: str = "",
    resource: str = "",
    **kwargs,
) -> dict:
    if not phone_number:
        return {"success": False, "error": "phone_number is required"}

    script = message or (
        f"This is FinOps dot A I. Critical alert on {resource}. "
        "Please review the dashboard immediately."
    )
    return {
        "success":     False,
        "phone":       phone_number,
        "script":      script,
        "data_source": "empty",
        "note":        "Phase 5: Set TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN in .env",
    }
