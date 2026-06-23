from __future__ import annotations

import json
from typing import Any, Dict, List

from agents.base_agent import BaseAgent


class IncidentAgent(BaseAgent):
    name = "Incident Agent"
    description = "Failure detection and alert triage via Azure Monitor"

    system_prompt = """
You are FinOps.AI's Incident Agent. Triage only live Azure Monitor alert data.
If no fired alerts are returned, say there are no active incidents.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message: str = payload.get("message", "")
        history = payload.get("history", [])
        alert_data = await self._fetch_active_alerts()
        context = f"Active Azure Monitor alerts:\n{json.dumps(alert_data, indent=2)}"

        response_text = await self.chat(
            user_message=message,
            conversation_history=history,
            context=context,
        )

        return {
            "response": response_text,
            "actions": self._build_incident_actions(alert_data),
            "sources": ["Azure Monitor Alerts", "Azure Service Health", "Application Insights"],
        }

    async def _fetch_active_alerts(self) -> List[Dict]:
        from services.azure_monitor_service import get_fired_alerts

        return await get_fired_alerts()

    def _build_incident_actions(self, alerts: List[Dict]) -> List[Dict]:
        return [
            {
                "source": "Incident Agent",
                "action_type": "incident_response",
                "alert_id": alert.get("id") or alert.get("alert_id"),
                "resource": alert.get("resource"),
                "proposed_action": f"Investigate {alert.get('name', 'Azure Monitor alert')}",
                "requires_approval": alert.get("severity") in ("Sev0", "Sev1", "critical"),
                "risk": "Low",
            }
            for alert in alerts
            if alert.get("state", "New") == "New"
        ]
