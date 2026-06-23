"""
mcp/finops_server/tools.py — FinOps MCP Server

Tools:
  get_cost_summary()         → MTD spend, budget, trend, by-service
  get_cost_by_service()      → Service-level breakdown for N days
  get_budget_status()        → Budget utilisation + breach risk
  get_advisor_recommendations() → Azure Advisor cost optimizations
  forecast_spend()           → XGBoost spend forecast
  detect_cost_anomalies()    → Isolation Forest anomaly scan

Used by:
  FinOps agent, Forecast agent, Anomaly agent, Optimization agent
"""

from mcp_layer.tool_registry import tool_registry


@tool_registry.register(
    name="get_cost_summary",
    server="finops",
    description="Month-to-date Azure spend: total, budget utilisation, daily trend, by-service",
    tags=["cost", "billing", "mtd"],
)
async def get_cost_summary(**kwargs) -> dict:
    from services.azure_cost_service import get_mtd_summary
    return await get_mtd_summary()


@tool_registry.register(
    name="get_cost_by_service",
    server="finops",
    description="Azure spend broken down by service for a given lookback window",
    tags=["cost", "service-breakdown"],
)
async def get_cost_by_service(days: int = 30, **kwargs) -> dict:
    from services.azure_cost_service import get_cost_by_service
    return await get_cost_by_service(days=int(days))


@tool_registry.register(
    name="get_budget_status",
    server="finops",
    description="Current budget utilisation percentage and breach risk assessment",
    tags=["budget", "cost"],
)
async def get_budget_status(**kwargs) -> dict:
    from services.azure_cost_service import get_mtd_summary
    data    = await get_mtd_summary()
    mtd     = data.get("mtd_spend", 0)
    budget  = data.get("budget_monthly", 25000)
    pct     = data.get("budget_utilisation_pct", 0)
    trend   = data.get("trend", [])

    # Simple linear breach forecast
    days_in_month = 30
    day_of_month  = len(trend)
    if day_of_month > 0 and mtd > 0:
        daily_avg    = mtd / day_of_month
        projected    = daily_avg * days_in_month
        breach_risk  = projected > budget
        breach_amt   = max(0, projected - budget)
    else:
        projected   = 0
        breach_risk = False
        breach_amt  = 0

    return {
        "mtd_spend":           round(mtd, 2),
        "budget":              budget,
        "currency":            data.get("currency", "USD"),
        "utilisation_pct":     pct,
        "projected_month_end": round(projected, 2),
        "breach_risk":         breach_risk,
        "breach_amount":       round(breach_amt, 2),
        "status": (
            "critical" if pct >= 90 else
            "warning"  if pct >= 75 else
            "healthy"
        ),
        "data_source":         data.get("data_source", "unknown"),
    }


@tool_registry.register(
    name="get_advisor_recommendations",
    server="finops",
    description="Azure Advisor cost, security, reliability, and performance recommendations",
    tags=["advisor", "optimization", "cost"],
)
async def get_advisor_recommendations(**kwargs) -> dict:
    from services.azure_resource_service import get_advisor_recommendations
    recs = await get_advisor_recommendations()
    return {
        "total":           len(recs),
        "recommendations": recs,
        "cost_recs":       [r for r in recs if r.get("category") == "Cost"],
        "data_source":     "live",
    }


@tool_registry.register(
    name="forecast_spend",
    server="finops",
    description="XGBoost spend forecast for 7, 14, or 30 days ahead",
    tags=["forecast", "ml", "xgboost"],
)
async def forecast_spend(horizon: int = 14, **kwargs) -> dict:
    from services.azure_cost_service import get_mtd_summary
    from ml.xgboost_forecast import forecast_spend as ml_forecast

    data  = await get_mtd_summary()
    trend = data.get("trend", [])

    if not trend:
        return {
            "method":       "no_data",
            "horizon_days": horizon,
            "predictions":  [],
            "note":         "No cost trend data available yet — deploy resources first.",
        }

    daily_costs = [t["amount"] for t in trend]
    result      = ml_forecast(daily_costs, horizon=int(horizon), trend_objects=trend)
    result["mtd_spend"]  = data.get("mtd_spend", 0)
    result["budget"]     = data.get("budget_monthly", 25000)
    result["data_source"] = data.get("data_source", "unknown")
    return result


@tool_registry.register(
    name="detect_cost_anomalies",
    server="finops",
    description="Isolation Forest anomaly detection on daily Azure spend data",
    tags=["anomaly", "ml", "isolation-forest"],
)
async def detect_cost_anomalies(**kwargs) -> dict:
    from services.azure_cost_service import get_mtd_summary
    from ml.isolation_forest import detect_cost_anomalies as ml_detect

    data  = await get_mtd_summary()
    trend = data.get("trend", [])

    if len(trend) < 5:
        return {
            "anomalies":   [],
            "total":       0,
            "ml_active":   False,
            "note":        f"Need at least 5 days of live cost data (have {len(trend)}).",
        }

    daily_costs = [t["amount"] for t in trend]
    anomalies   = ml_detect(daily_costs, trend)

    return {
        "anomalies":  anomalies,
        "total":      len(anomalies),
        "critical":   sum(1 for a in anomalies if a.get("severity") == "critical"),
        "warning":    sum(1 for a in anomalies if a.get("severity") == "warning"),
        "ml_active":  True,
        "data_source": data.get("data_source", "unknown"),
    }
