"""
Real anomaly and recommendation endpoints.

No mock anomalies are returned. Empty subscriptions stay empty until Azure Cost
Management has enough daily cost points for Isolation Forest.
"""

from fastapi import APIRouter, Depends

from services.azure_account import AzureAccount, account_from_headers

router = APIRouter()


def _build_summary(items: list) -> dict:
    return {
        "total": len(items),
        "critical": sum(1 for item in items if item.get("severity") == "critical"),
        "warning": sum(1 for item in items if item.get("severity") == "warning"),
        "investigating": sum(1 for item in items if item.get("status") == "investigating"),
        "resolved_today": sum(1 for item in items if item.get("severity") == "resolved"),
        "items": items,
    }


@router.get("/")
async def list_anomalies(account: AzureAccount = Depends(account_from_headers)):
    try:
        from services.azure_cost_service import get_mtd_summary
        from ml.isolation_forest import detect_cost_anomalies

        cost_data = await get_mtd_summary(account)
        trend = cost_data.get("trend", [])
        if len(trend) >= 5:
            daily_costs = [point["amount"] for point in trend]
            items = detect_cost_anomalies(daily_costs, trend)
            return {**_build_summary(items), "data_source": cost_data.get("data_source", "live")}

        return {
            **_build_summary([]),
            "data_source": "empty",
            "note": "Need at least five daily Azure Cost Management points before anomaly detection can run.",
        }
    except Exception as exc:
        return {**_build_summary([]), "data_source": "error", "error": str(exc)}


@router.get("/alerts")
async def list_alerts():
    try:
        from services.azure_monitor_service import get_fired_alerts

        alerts = await get_fired_alerts()
        return {"alerts": alerts, "data_source": "live"}
    except Exception as exc:
        return {"alerts": [], "data_source": "error", "error": str(exc)}


@router.get("/recommendations")
async def list_recommendations(account: AzureAccount = Depends(account_from_headers)):
    try:
        from services.azure_resource_service import get_advisor_recommendations

        recs = await get_advisor_recommendations(account)
        return {"recommendations": recs, "total": len(recs), "data_source": "live"}
    except Exception as exc:
        return {"recommendations": [], "total": 0, "data_source": "error", "error": str(exc)}
