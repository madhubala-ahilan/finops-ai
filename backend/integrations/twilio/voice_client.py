"""
integrations/twilio/voice_client.py
Twilio programmable voice — outbound alert calls.

Requires in .env:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM_NUMBER
  VOICE_ALERT_PHONE    (default recipient)

Architecture role: called by Alert Agent for P0 incidents.
"""

from __future__ import annotations
import logging
import urllib.parse
import base64

import httpx

logger = logging.getLogger("finops.twilio")


async def make_alert_call(phone: str, message: str) -> dict:
    """
    Initiate an outbound Twilio voice call that reads `message` via TTS.

    Returns {"status": "initiated", "call_sid": "..."} on success.
    Raises RuntimeError if Twilio credentials are not configured.
    """
    from config import settings

    account_sid  = getattr(settings, "TWILIO_ACCOUNT_SID",  "")
    auth_token   = getattr(settings, "TWILIO_AUTH_TOKEN",   "")
    from_number  = getattr(settings, "TWILIO_FROM_NUMBER",  "")

    if not all([account_sid, auth_token, from_number]):
        raise RuntimeError(
            "Twilio credentials not configured. "
            "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER to .env."
        )

    # TwiML that reads the message
    twiml = f"<Response><Say voice='alice'>{message}</Say></Response>"

    url  = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()

    payload = {
        "To":    phone,
        "From":  from_number,
        "Twiml": twiml,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            url,
            data=urllib.parse.urlencode(payload),
            headers={
                "Authorization":  f"Basic {auth}",
                "Content-Type":   "application/x-www-form-urlencoded",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    call_sid = data.get("sid", "unknown")
    logger.info("Twilio call initiated: SID=%s to=%s", call_sid, phone)
    return {"status": "initiated", "call_sid": call_sid, "to": phone}
