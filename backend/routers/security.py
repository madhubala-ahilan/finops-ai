from fastapi import APIRouter, Depends

from agents.security_agent import get_security_posture
from services.azure_account import AzureAccount, account_from_headers, reset_current_account, set_current_account
from services.azure_policy_service import get_policy_compliance_summary

router = APIRouter()


@router.get("/posture")
async def security_posture(account: AzureAccount = Depends(account_from_headers)):
    """Live Defender for Cloud / Resource Graph security posture plus Policy compliance."""
    token = set_current_account(account)
    try:
        security = await get_security_posture()
        policy = security.get("policy") or await get_policy_compliance_summary()
        return {
            "security": security,
            "policy": policy,
            "total_findings": security.get("total", 0),
            "total_non_compliant": policy.get("total_non_compliant", 0),
            "data_sources": {
                "security": security.get("data_source", "unknown"),
                "policy": policy.get("data_source", "unknown"),
            },
        }
    finally:
        reset_current_account(token)
