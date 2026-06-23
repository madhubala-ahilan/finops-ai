"""
/api/v1/cloudops — Resource health map and CloudOps agent queries.
Now uses real Azure Resource Graph (FREE API).
"""

from fastapi import APIRouter, Depends
from services.azure_resource_service import (
    get_all_resources,
    get_resource_health_summary,
    get_advisor_recommendations,
)
from services.azure_account import AzureAccount, account_from_headers
from agents.router import agent_router
from models.schemas import AgentName

router = APIRouter()


@router.get("/resources")
async def list_resources(account: AzureAccount = Depends(account_from_headers)):
    """
    Full Azure resource inventory from Resource Graph.
    API cost: FREE (Resource Graph queries have no per-call charge).
    """
    return await get_all_resources(account)


@router.get("/health")
async def resource_health(account: AzureAccount = Depends(account_from_headers)):
    """
    Azure Resource Health summary — availability states across subscription.
    API cost: FREE.
    """
    return await get_resource_health_summary(account)


@router.get("/advisor")
async def advisor_recommendations(account: AzureAccount = Depends(account_from_headers)):
    """
    Azure Advisor recommendations (cost, security, reliability, performance).
    API cost: FREE.
    """
    recs = await get_advisor_recommendations(account)
    return {"total": len(recs), "recommendations": recs}


@router.get("/resources/{resource_name}")
async def get_resource_detail(resource_name: str):
    """Get CloudOps agent analysis for a specific resource."""
    agent = agent_router.get_agent(AgentName.CLOUDOPS)
    result = await agent.run({
        "message": f"Give me a detailed health analysis for {resource_name}",
        "history": [],
    })
    return {"resource": resource_name, "analysis": result["response"]}


@router.post("/self-heal/{resource_name}")
async def trigger_self_heal(resource_name: str):
    """Trigger CloudOps agent to propose a self-healing action."""
    agent = agent_router.get_agent(AgentName.CLOUDOPS)
    result = await agent.run({
        "message": f"Propose a self-healing action for {resource_name}",
        "history": [],
    })
    return {
        "resource": resource_name,
        "proposed_actions": result.get("actions", []),
        "analysis": result["response"],
    }
