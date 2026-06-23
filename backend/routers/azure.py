from __future__ import annotations

from fastapi import APIRouter, Depends

from services.azure_account import AzureAccount, account_from_headers

router = APIRouter()


@router.get("/connection")
async def validate_connection(account: AzureAccount = Depends(account_from_headers)):
    try:
        from services.azure_resource_service import get_all_resources

        resources = await get_all_resources(account)
        if resources.get("data_source") == "error":
            return {
                "connected": False,
                "subscription_id": account.subscription_id,
                "error": resources.get("error"),
            }
        return {
            "connected": True,
            "subscription_id": account.subscription_id,
            "resource_count": resources.get("total", 0),
        }
    except Exception as exc:
        return {
            "connected": False,
            "subscription_id": account.subscription_id,
            "error": str(exc),
        }
