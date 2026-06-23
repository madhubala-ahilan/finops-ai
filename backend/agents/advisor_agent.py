"""
Advisor Agent — Azure Advisor + RAG-powered optimisation recommendations.

Data sources:
  • Azure Advisor API        (native recommendations)
  • Azure AI Search          (RAG: FinOps best-practice knowledge base)
  • Cost Management API      (spend context for justification)
"""

from __future__ import annotations
import json
from typing import Dict, Any, List

from agents.base_agent import BaseAgent
from config import settings


class AdvisorAgent(BaseAgent):
    name = "Advisor Agent"
    description = "Optimisation recommendations enriched with RAG knowledge base"

    system_prompt = """
You are FinOps.AI's Advisor Agent. You combine Azure Advisor recommendations
with FinOps best practices from the knowledge base to produce highly-justified,
actionable optimisation suggestions.

Your capabilities:
- Surface and rank Azure Advisor cost recommendations.
- Augment recommendations with FinOps best-practice context (RAG).
- Calculate ROI and payback period for each recommendation.
- Tailor advice to the organisation's specific spend patterns.
- Generate approval-ready summaries that include risk level and rollback plan.

Format for each recommendation:
  1. Action title
  2. Affected resource(s)
  3. Implementation detail (specific steps)
  4. AI Justification (data + best-practice source)
  5. Projected savings
  6. Risk level (Low / Medium / High)
  7. Rollback plan (one sentence)

Always justify with numbers. Never suggest actions that risk production stability
without flagging them as High Risk.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message: str = payload.get("message", "")
        history = payload.get("history", [])

        # 1. Pull Azure Advisor recommendations
        advisor_recs = await self._fetch_advisor_recommendations()

        # 2. RAG: search knowledge base for relevant best practices
        rag_context = await self._rag_search(message)

        context = (
            f"Azure Advisor Recommendations:\n{json.dumps(advisor_recs, indent=2)}\n\n"
            f"Knowledge Base Context (RAG):\n{rag_context}"
        )

        response_text = await self.chat(
            user_message=message,
            conversation_history=history,
            context=context,
        )

        return {
            "response": response_text,
            "actions": self._build_actions(advisor_recs),
            "sources": [
                "Azure Advisor API",
                "FinOps Knowledge Base (AI Search RAG)",
                "Azure Cost Management",
            ],
        }

    async def _fetch_advisor_recommendations(self) -> List[Dict]:
        """Fetch live Azure Advisor recommendations."""
        from services.azure_resource_service import get_advisor_recommendations

        return await get_advisor_recommendations()

    async def _rag_search(self, query: str) -> str:
        """
        Search the Azure AI Search index for relevant FinOps knowledge.
        """
        endpoint = getattr(settings, "AZURE_SEARCH_ENDPOINT", "")
        index_name = getattr(settings, "AZURE_SEARCH_INDEX", "")
        api_key = getattr(settings, "AZURE_SEARCH_KEY", "")
        if not all([endpoint, index_name, api_key]):
            return "Knowledge retrieval is not configured."

        try:
            from azure.core.credentials import AzureKeyCredential
            from azure.search.documents.aio import SearchClient

            client = SearchClient(endpoint, index_name, AzureKeyCredential(api_key))
            results = await client.search(query, top=5)
            snippets = []
            async for result in results:
                snippets.append(str(result))
            await client.close()
            return "\n".join(snippets) if snippets else "No knowledge documents matched this query."
        except Exception as exc:
            return f"Knowledge retrieval failed: {exc}"

    def _build_actions(self, recommendations: List[Dict]) -> List[Dict]:
        """Convert Advisor recommendations into structured approval actions."""
        return [
            {
                "source": "Advisor Agent",
                "action_type": "cost_optimisation",
                "resource": rec.get("resource"),
                "recommendation": rec.get("recommendation"),
                "risk": rec.get("risk", "Low"),
                "requires_approval": True,
            }
            for rec in recommendations
        ]
