"""
agents/forecasting_agent.py — Forecasting Agent.

Architecture Layer: Agent Layer → Forecast Agent
ML backend: ml.xgboost_forecast (Phase 2B, ACTIVE)
LLM backend: Azure OpenAI GPT-4o (Phase 6, PENDING)

Flow:
  1. Fetch daily cost trend from Azure Cost Management.
  2. Run XGBoost (or linear fallback) to generate predictions.
  3. Detect budget-breach risk and trigger AlertAgent if needed.
  4. (Phase 6) Use GPT-4o to narrate the forecast in plain English.
  5. Return structured forecast data for the API + chart.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from agents.base_agent import BaseAgent

logger = logging.getLogger("finops.forecasting_agent")


class ForecastingAgent(BaseAgent):
    name        = "Forecasting Agent"
    description = "XGBoost spend prediction + budget-breach early warning"

    system_prompt = """
You are FinOps.AI's Forecasting Agent.

Your job:
- Interpret cloud spend forecasts for non-technical stakeholders.
- Explain the trend in 2-3 sentences.
- Highlight if a budget breach is likely and by how much.
- Give one actionable recommendation.

Format your response as JSON:
{
  "summary":     "...",
  "trend":       "increasing|stable|decreasing",
  "breach_risk": "high|medium|low|none",
  "breach_amount": 0.0,
  "recommendation": "...",
  "confidence":  "high|medium|low"
}
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a spend forecast.

        Payload keys:
          message   (str)  User query or "generate forecast"
          history   (list) Conversation history
          horizon   (int)  Days to forecast (default 14)
        """
        message = payload.get("message", "generate forecast")
        horizon = int(payload.get("horizon", 14))

        # ── Step 1: Fetch cost trend ───────────────────────────────────────────
        cost_data = await self._fetch_cost_data()
        trend     = cost_data.get("trend", [])
        mtd       = cost_data.get("mtd_spend", 0)
        budget    = cost_data.get("budget_monthly", 25000)

        # ── Step 2: Run XGBoost forecast ──────────────────────────────────────
        forecast_result = {}
        if trend:
            try:
                from ml.xgboost_forecast import forecast_spend
                daily_costs    = [t["amount"] for t in trend]
                forecast_result = forecast_spend(daily_costs, horizon=horizon, trend_objects=trend)
                logger.info(
                    f"[ForecastingAgent] {forecast_result.get('method')} "
                    f"| horizon={horizon}d "
                    f"| MAE={forecast_result.get('mae', '?')}"
                )
            except Exception as exc:
                logger.warning(f"[ForecastingAgent] ML skipped: {exc}")

        # ── Step 3: Budget breach detection ───────────────────────────────────
        predictions      = forecast_result.get("predictions", [])
        total_predicted  = mtd + sum(predictions)
        breach_risk      = total_predicted > budget
        breach_amount    = max(0, total_predicted - budget)

        if breach_risk and breach_amount > 500:
            try:
                from agents.alert_agent import dispatch_alert
                await dispatch_alert(
                    title="Budget breach predicted by ForecastingAgent",
                    severity="critical",
                    resource="subscription/prod",
                    detail=f"Forecast total ${total_predicted:,.0f} vs ${budget:,.0f} budget",
                    delta=f"+${breach_amount:,.0f}",
                )
            except Exception as exc:
                logger.warning(f"[ForecastingAgent] Alert skipped: {exc}")

        # ── Step 4: LLM narrative (stub until OpenAI configured) ──────────────
        context = (
            f"MTD spend: ${mtd:,.2f}\n"
            f"Budget: ${budget:,.0f}/month\n"
            f"Forecast method: {forecast_result.get('method', 'none')}\n"
            f"Horizon: {horizon} days\n"
            f"Sum of predictions: ${sum(predictions):,.0f}\n"
            f"Budget breach: {'YES' if breach_risk else 'NO'} "
            f"(${breach_amount:,.0f} over)" if breach_risk else ""
        )
        narrative = await self.chat(
            user_message=message,
            context=context,
        )

        # ── Step 5: Return ─────────────────────────────────────────────────────
        return {
            "response":       narrative,
            "forecast_data": {
                "mtd_spend":       round(mtd, 2),
                "budget":          budget,
                "horizon_days":    horizon,
                "method":          forecast_result.get("method", "none"),
                "predictions":     predictions,
                "confidence_lo":   forecast_result.get("confidence_lo", []),
                "confidence_hi":   forecast_result.get("confidence_hi", []),
                "series":          forecast_result.get("series", []),
                "mae":             forecast_result.get("mae", 0),
                "rmse":            forecast_result.get("rmse", 0),
                "breach_risk":     breach_risk,
                "breach_amount":   round(breach_amount, 2),
                "total_predicted": round(total_predicted, 2),
                "data_source":     cost_data.get("data_source", "unknown"),
            },
            "actions": [],
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _fetch_cost_data(self) -> Dict[str, Any]:
        try:
            from services.azure_cost_service import get_mtd_summary
            return await get_mtd_summary()
        except Exception as exc:
            logger.warning(f"[ForecastingAgent] Cost fetch failed: {exc}")
            return {
                "trend": [], "mtd_spend": 0,
                "budget_monthly": 25000,
                "by_service": {},
                "data_source": "error",
            }
