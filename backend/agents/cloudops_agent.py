from __future__ import annotations

import json
from typing import Any, Dict, List

from agents.base_agent import BaseAgent


class CloudOpsAgent(BaseAgent):
    name = "CloudOps Agent"
    description = "Resource health monitoring across Azure subscriptions"

    system_prompt = """
You are FinOps.AI's CloudOps Agent. Use only live Azure Resource Graph,
Resource Health, Advisor, and Monitor context. If a metric is not available,
say it is unavailable instead of inventing values.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message: str = payload.get("message", "")
        history = payload.get("history", [])

        resource_data = await self._fetch_resource_health()
        context = f"Azure resource snapshot:\n{json.dumps(resource_data, indent=2)}"

        response_text = await self.chat(
            user_message=message,
            conversation_history=history,
            context=context,
        )

        return {
            "response": response_text,
            "actions": self._propose_remediations(resource_data),
            "sources": ["Azure Resource Health API", "Azure Resource Graph", "Azure Monitor Metrics"],
            "resource_snapshot": resource_data,
        }

    async def _fetch_resource_health(self) -> Dict[str, Any]:
        from services.azure_resource_service import get_all_resources, get_resource_health_summary

        inventory = await get_all_resources()
        health = await get_resource_health_summary()
        return {**inventory, "health_summary": health}

    def _propose_remediations(self, resource_data: Dict) -> List[Dict]:
        actions = []
        for resource in resource_data.get("resources", []):
            status = resource.get("status")
            if status not in ("critical", "warning"):
                continue
            name = resource.get("name", "")
            actions.append({
                "source": "CloudOps Agent",
                "action_type": "self_healing",
                "resource": name,
                "issue": resource.get("issue", "Azure health state requires review"),
                "proposed_action": f"Investigate and remediate {name}",
                "requires_approval": status == "critical",
                "risk": "Low" if status == "warning" else "Medium",
            })
        return actions
