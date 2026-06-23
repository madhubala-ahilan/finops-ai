from __future__ import annotations

import logging
from typing import Any, Dict

from agents.base_agent import BaseAgent

logger = logging.getLogger("finops.anomaly_agent")


class AnomalyAgent(BaseAgent):
    name = "Anomaly Agent"
    description = "Isolation Forest cost-spike detection on live Azure cost data"

    system_prompt = """
You are FinOps.AI's Anomaly Detection Agent.

Use only live Azure cost data supplied by tools. If there is not enough data,
say that anomaly detection is blank until Azure Cost Management has enough
daily points. Do not invent resources, costs, anomalies, or remediations.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = payload.get("message", "auto")
        cost_data = await self._fetch_cost_data()
        trend = cost_data.get("trend", [])
        by_service = cost_data.get("by_service", {})

        anomalies = []
        if len(trend) >= 5:
            try:
                from ml.isolation_forest import detect_cost_anomalies

                daily_costs = [point["amount"] for point in trend]
                anomalies = detect_cost_anomalies(daily_costs, trend)
            except Exception as exc:
                logger.warning("[AnomalyAgent] ML skipped: %s", exc)

        context = (
            f"MTD spend: {cost_data.get('mtd_spend', 0)}\n"
            f"Budget: {cost_data.get('budget_monthly', 0)}\n"
            f"Daily cost points: {len(trend)}\n"
            f"Anomalies found: {len(anomalies)}\n"
            f"Top services: {list(by_service.items())[:3]}"
        )
        narrative = await self.chat(
            user_message=message if message != "auto" else "Analyze Azure cost anomalies.",
            context=context,
        )

        return {
            "response": narrative,
            "anomalies": anomalies,
            "total": len(anomalies),
            "critical": sum(1 for item in anomalies if item.get("severity") == "critical"),
            "warning": sum(1 for item in anomalies if item.get("severity") == "warning"),
            "ml_active": bool(anomalies),
            "data_source": cost_data.get("data_source", "unknown"),
            "actions": [],
        }

    async def _fetch_cost_data(self) -> Dict[str, Any]:
        try:
            from services.azure_cost_service import get_mtd_summary

            return await get_mtd_summary()
        except Exception as exc:
            logger.warning("[AnomalyAgent] Cost fetch failed: %s", exc)
            return {"trend": [], "mtd_spend": 0, "by_service": {}, "data_source": "error"}
