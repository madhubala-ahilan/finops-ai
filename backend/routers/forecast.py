from __future__ import annotations

from fastapi import APIRouter, Depends

from services.azure_account import AzureAccount, account_from_headers
from services.azure_cost_service import get_mtd_summary

router = APIRouter(tags=["Forecast"])


async def _forecast(days: int, account: AzureAccount) -> dict:
    data = await get_mtd_summary(account)
    trend = data.get("trend", [])
    if not trend:
        return {
            "horizon_days": days,
            "predictions": [],
            "data_source": "empty",
            "note": "Azure has not returned any daily cost points yet.",
        }

    from ml.xgboost_forecast import forecast_spend

    result = forecast_spend(
        [point["amount"] for point in trend],
        horizon=days,
        trend_objects=trend,
    )
    result["data_source"] = data.get("data_source", "live")
    result["mtd_spend"] = data.get("mtd_spend", 0)
    result["budget"] = data.get("budget_monthly", 0)
    result["currency"] = data.get("currency", "USD")
    if len(trend) < 5:
        result["note"] = (
            f"Limited-history forecast using {len(trend)} live Azure daily point(s). "
            "It will switch to linear regression after 5 days and XGBoost after 14 days."
        )
    return result


@router.get("/")
async def forecast_default(account: AzureAccount = Depends(account_from_headers)):
    return await _forecast(30, account)


@router.get("/7d")
async def forecast_7d(account: AzureAccount = Depends(account_from_headers)):
    return await _forecast(7, account)


@router.get("/30d")
async def forecast_30d(account: AzureAccount = Depends(account_from_headers)):
    return await _forecast(30, account)


@router.get("/90d")
async def forecast_90d(account: AzureAccount = Depends(account_from_headers)):
    return await _forecast(90, account)
