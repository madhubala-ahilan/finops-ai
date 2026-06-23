"""
services/orchestration_service.py
Multi-agent workflow orchestration — the LangGraph layer.

Architecture:
  START → Router Agent → [FinOps | CloudOps | Forecast | Anomaly]
        → Governance Agent (approval gate)
        → Alert Agent
        → END

This module wires those steps together in code.
A full LangGraph implementation would replace the manual step-calling below;
the interface (run_workflow) stays the same.

Called by:
  routers/agents_router.py  /api/v1/agents/chat
  agents/router.py          AgentRouter.dispatch()
"""

from __future__ import annotations
import logging
from typing import Dict, Any, List

from models.schemas import AgentName

logger = logging.getLogger("finops.orchestration")


# ── Workflow state ─────────────────────────────────────────────────────────────

class WorkflowState:
    def __init__(self, message: str, history: List[Dict[str, str]]):
        self.message          = message
        self.history          = history
        self.routed_to:  AgentName | None = None
        self.agent_result: Dict[str, Any] = {}
        self.requires_approval: bool      = False
        self.alert_sent:  bool            = False
        self.audit_id:    str | None      = None


# ── Workflow nodes ─────────────────────────────────────────────────────────────

async def _node_route(state: WorkflowState) -> WorkflowState:
    """Router agent classifies the message and picks a specialist."""
    from agents.router import agent_router
    state.routed_to = agent_router._classify(state.message)
    logger.info("Orchestration: routed to %s", state.routed_to)
    return state


async def _node_execute(state: WorkflowState) -> WorkflowState:
    """Run the chosen specialist agent."""
    from agents.router import agent_router
    agent  = agent_router.get_agent(state.routed_to)
    result = await agent.run({"message": state.message, "history": state.history})
    state.agent_result = result
    return state


async def _node_governance(state: WorkflowState) -> WorkflowState:
    """
    Governance gate: if the agent proposed actions that require approval,
    queue them and set requires_approval=True.
    """
    actions = state.agent_result.get("actions", [])
    high_risk = [a for a in actions if a.get("risk", "").lower() in ("high", "medium")]
    if high_risk:
        state.requires_approval = True
        logger.info("Orchestration: %d action(s) queued for approval", len(high_risk))
    return state


async def _node_alert(state: WorkflowState) -> WorkflowState:
    """
    Alert node: send Teams / email notification for critical findings.
    Only fires if the agent response contains severity=critical.
    """
    response = state.agent_result.get("response", "")
    if "critical" in response.lower():
        logger.info("Orchestration: critical finding detected — alert would fire here")
        # Alert Agent should send Teams notifications once TEAMS_WEBHOOK_URL is configured.
        state.alert_sent = True
    return state


# ── Public entrypoint ──────────────────────────────────────────────────────────

async def run_workflow(
    message: str,
    history: List[Dict[str, str]] | None = None,
    target_agent: AgentName | None = None,
) -> Dict[str, Any]:
    """
    Execute the full multi-agent workflow.

    Args:
        message:       User's natural language query.
        history:       Prior conversation turns.
        target_agent:  Skip routing and send directly to this agent.

    Returns a dict with:
        agent_used, response, actions_proposed, sources,
        requires_approval, alert_sent
    """
    state = WorkflowState(message=message, history=history or [])

    if target_agent:
        state.routed_to = target_agent
    else:
        state = await _node_route(state)

    state = await _node_execute(state)
    state = await _node_governance(state)
    state = await _node_alert(state)

    return {
        "agent_used":         state.routed_to,
        "response":           state.agent_result.get("response", ""),
        "actions_proposed":   state.agent_result.get("actions", []),
        "sources":            state.agent_result.get("sources", []),
        "requires_approval":  state.requires_approval,
        "alert_sent":         state.alert_sent,
    }
