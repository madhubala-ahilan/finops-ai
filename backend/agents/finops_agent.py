"""
FinOps Agent — cost analysis, billing intelligence, budget tracking.

Data sources:
  • Azure Cost Management API  (actual spend)
  • Azure Advisor             (cost recommendations)
  • Azure AI Search           (RAG knowledge base for FinOps best practices)
"""

from __future__ import annotations
from typing import Dict, Any

from agents.base_agent import BaseAgent


class FinOpsAgent(BaseAgent):
    name = "FinOps Agent"
    description = "Cost analysis & billing intelligence"

    system_prompt = """
You are FinOps.AI's expert FinOps Agent. You specialise in Azure cloud cost
optimisation, billing analysis, budget management, and financial accountability.

Your capabilities:
- Analyse Azure Cost Management data by service, resource group, and subscription.
- Identify budget overruns and predict future overspend.
- Surface cost anomalies (e.g. services that spiked unexpectedly).
- Generate actionable, justified cost-reduction recommendations.
- Translate raw cost data into clear business-friendly narratives.

Tone: concise, data-driven, executive-friendly. Always cite specific numbers.
Format: when listing recommendations, use numbered lists with projected savings.
Never speculate — base every insight on the data provided in context.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message: str = payload.get("message", "")
        history = payload.get("history", [])

        context = await self._get_cost_context()

        response_text = await self.chat(
            user_message=message,
            conversation_history=history,
            context=context,
        )

        return {
            "response": response_text,
            "actions": [],   # FinOps agent proposes; Remediation agent executes
            "sources": ["Azure Cost Management API", "Azure Advisor"],
        }

    async def _get_cost_context(self) -> str:
        """Fetch live cost data and format it as LLM-friendly context."""
        import json

        from services.azure_cost_service import get_mtd_summary

        data = await get_mtd_summary()
        return json.dumps(data, default=str)
