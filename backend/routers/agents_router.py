"""
/api/v1/agents — Agent control, status, and chat endpoints.
"""

from fastapi import APIRouter, HTTPException
from models.schemas import (
    AgentChatRequest, AgentChatResponse,
    AgentToggleRequest, AgentStatus, AgentName,
)
from agents.router import agent_router

router = APIRouter()


@router.get("/", response_model=list[dict])
async def list_agents():
    """Return status of all 7 agents."""
    return agent_router.all_statuses()


@router.patch("/{agent_name}/toggle")
async def toggle_agent(agent_name: AgentName, body: AgentToggleRequest):
    """Enable or disable a specific agent."""
    try:
        agent_router.toggle(agent_name, body.enabled)
        return {"agent": agent_name, "enabled": body.enabled}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")


@router.post("/chat", response_model=AgentChatResponse)
async def chat(request: AgentChatRequest):
    """
    Send a message to the best-fit agent (auto-routed) or a specific agent.
    Returns the agent's response plus any proposed actions.
    """
    try:
        return await agent_router.dispatch(request)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")
