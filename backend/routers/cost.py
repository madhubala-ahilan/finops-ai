"""
/api/v1/cost — Cost summary, trends, and forecasts.
Now uses real AzureCostService (Cost Management API — FREE).
"""

from fastapi import APIRouter, Depends, Query
from services.azure_cost_service import get_mtd_summary, get_cost_by_service, get_cost_analysis
from services.azure_account import AzureAccount, account_from_headers

router = APIRouter()


@router.get("/summary", response_model=dict)
async def cost_summary(account: AzureAccount = Depends(account_from_headers)):
    """
    Current month-to-date spend summary with daily trend and service breakdown.
    Data source: Azure Cost Management API (FREE — no per-call charge).
    """
    return await get_mtd_summary(account)


@router.get("/forecast", response_model=dict)
async def get_forecast(account: AzureAccount = Depends(account_from_headers)):
    """Legacy forecast route kept generic by using the request's Azure account."""
    from routers.forecast import _forecast

    return await _forecast(30, account)


@router.get("/by-service")
async def cost_by_service(
    account: AzureAccount = Depends(account_from_headers),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days")
):
    """
    Cost breakdown by Azure service for the given period.
    Data source: Azure Cost Management API (FREE).
    """
    return await get_cost_by_service(days=days, account=account)


@router.get("/analysis")
async def cost_analysis(
    account: AzureAccount = Depends(account_from_headers),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    service: str = Query("", description="Optional service/category filter"),
    resource_group: str = Query("", description="Optional resource group filter"),
    region: str = Query("", description="Optional Azure region filter"),
    resource_type: str = Query("", description="Optional ARM resource type filter"),
    resource_ids: str = Query("", description="Comma-separated ARM resource IDs to compare"),
    start_date: str = Query("", description="Inclusive start date YYYY-MM-DD"),
    end_date: str = Query("", description="Inclusive end date YYYY-MM-DD"),
):
    """
    Detailed resource/component cost explorer backed by Azure Consumption
    usageDetails. This powers resource-level comparisons without issuing many
    Cost Management grouping queries.
    """
    ids = [item.strip() for item in resource_ids.split(",") if item.strip()]
    return await get_cost_analysis(
        days=days,
        account=account,
        service=service,
        resource_group=resource_group,
        region=region,
        resource_type=resource_type,
        resource_ids=ids,
        start_date=start_date,
        end_date=end_date,
    )
