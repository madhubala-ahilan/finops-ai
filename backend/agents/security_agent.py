from __future__ import annotations

import json
from typing import Any, Dict

from agents.base_agent import BaseAgent


class SecurityAgent(BaseAgent):
    name = "Security Agent"
    description = "Azure security posture, policy compliance, and Defender findings"

    system_prompt = """
You are FinOps.AI's Security Agent. You inspect Azure security posture using
live Azure security, policy, and resource data. Do not invent findings. If the
tenant has not enabled Microsoft Defender for Cloud or Policy Insights access,
explain that clearly and return the live empty/not-configured state.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = payload.get("message", "")
        findings = await get_security_posture()
        context = json.dumps(findings, indent=2, default=str)
        response = await self.chat(
            user_message=message,
            conversation_history=payload.get("history", []),
            context=context,
        )
        return {
            "response": response,
            "actions": [],
            "sources": ["Azure Resource Graph securityresources", "Azure Policy Insights"],
            "security": findings,
        }


async def get_security_posture() -> Dict[str, Any]:
    from services.azure_account import current_account
    from services.azure_policy_service import get_policy_compliance_summary

    try:
        from azure.mgmt.resourcegraph import ResourceGraphClient
        from azure.mgmt.resourcegraph.models import QueryRequest

        account = current_account()
        client = ResourceGraphClient(account.credential())
        query = """
securityresources
| project id, name, type, properties, subscriptionId
| limit 100
"""
        result = client.resources(QueryRequest(subscriptions=[account.subscription_id], query=query))
        rows = getattr(result, "data", []) or []
        policy = await get_policy_compliance_summary()
        findings = rows or [_demo_security_finding(account.subscription_id)]
        return {
            "data_source": "live" if rows else "demo",
            "total": len(findings),
            "live_total": len(rows),
            "findings": findings,
            "policy": policy,
            "note": None if rows else (
                "No live securityresources rows returned. Showing one clearly-labelled demo finding "
                "so the Security page workflow can be reviewed without weakening Azure resources."
            ),
        }
    except Exception as exc:
        policy = await get_policy_compliance_summary()
        return {
            "data_source": "error",
            "total": 0,
            "findings": [],
            "policy": policy,
            "error": str(exc),
            "note": "Security posture requires Microsoft Defender for Cloud and Resource Graph securityresources access.",
        }


def _demo_security_finding(subscription_id: str) -> Dict[str, Any]:
    return {
        "id": f"/subscriptions/{subscription_id}/providers/Microsoft.Security/demoFindings/demo-public-access-review",
        "name": "Demo: Storage public access review",
        "type": "microsoft.security/demoFindings",
        "subscriptionId": subscription_id,
        "is_demo": True,
        "severity": "Medium",
        "properties": {
            "displayName": "Demo: Storage account may allow public access",
            "status": {"code": "Unhealthy"},
            "resourceDetails": {"source": "FinOps.AI demo finding"},
            "remediationDescription": (
                "Review storage account public network access, blob anonymous access, "
                "and private endpoint configuration."
            ),
        },
    }
