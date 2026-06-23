"""
AgentRouter — the central dispatcher for the multi-agent system.

Responsibilities:
  1. Classify incoming messages to pick the best specialist agent.
  2. Fan-out to multiple agents when needed (e.g. anomaly + remediation).
  3. Maintain a registry of all 7 agents with enable/disable control.
  4. Expose per-agent stats for the dashboard health panel.
"""

from __future__ import annotations
import logging
from typing import Dict, Optional

from agents.base_agent import BaseAgent
from agents.finops_agent import FinOpsAgent
from agents.anomaly_agent import AnomalyAgent
from agents.forecasting_agent import ForecastingAgent
from agents.advisor_agent import AdvisorAgent
from agents.cloudops_agent import CloudOpsAgent
from agents.security_agent import SecurityAgent
from agents.incident_agent import IncidentAgent
from agents.remediation_agent import RemediationAgent
from models.schemas import AgentName, AgentChatRequest, AgentChatResponse

logger = logging.getLogger(__name__)


# ── Routing keyword map ────────────────────────────────────────────────────────
# Maps intent keywords → agent enum. Router LLM will be more accurate,
# but this is a fast fallback for obvious intents.

KEYWORD_MAP: Dict[str, AgentName] = {
    # FinOps
    "cost": AgentName.FINOPS,
    "spend": AgentName.FINOPS,
    "billing": AgentName.FINOPS,
    "budget": AgentName.FINOPS,
    "invoice": AgentName.FINOPS,
    "price": AgentName.FINOPS,
    # Forecasting
    "forecast": AgentName.FORECASTING,
    "predict": AgentName.FORECASTING,
    "trend": AgentName.FORECASTING,
    "projection": AgentName.FORECASTING,
    # Anomaly
    "anomaly": AgentName.ANOMALY,
    "spike": AgentName.ANOMALY,
    "unusual": AgentName.ANOMALY,
    "alert": AgentName.ANOMALY,
    "waste": AgentName.ANOMALY,
    "idle": AgentName.ANOMALY,
    # CloudOps
    "resource": AgentName.CLOUDOPS,
    "health": AgentName.CLOUDOPS,
    "vm": AgentName.CLOUDOPS,
    "aks": AgentName.CLOUDOPS,
    "kubernetes": AgentName.CLOUDOPS,
    "database": AgentName.CLOUDOPS,
    # Security
    "security": AgentName.SECURITY,
    "defender": AgentName.SECURITY,
    "policy": AgentName.SECURITY,
    "compliance": AgentName.SECURITY,
    "vulnerability": AgentName.SECURITY,
    "secure": AgentName.SECURITY,
    # Incident
    "incident": AgentName.INCIDENT,
    "outage": AgentName.INCIDENT,
    "failure": AgentName.INCIDENT,
    "down": AgentName.INCIDENT,
    "error": AgentName.INCIDENT,
    # Remediation
    "fix": AgentName.REMEDIATION,
    "remediate": AgentName.REMEDIATION,
    "scale": AgentName.REMEDIATION,
    "resize": AgentName.REMEDIATION,
    "delete": AgentName.REMEDIATION,
    "approve": AgentName.REMEDIATION,
    # Advisor
    "recommend": AgentName.ADVISOR,
    "optimize": AgentName.ADVISOR,
    "suggestion": AgentName.ADVISOR,
    "improve": AgentName.ADVISOR,
    "reserved": AgentName.ADVISOR,
}


class AgentRouter:
    """
    Singleton registry + dispatcher for all 7 agents.
    """

    def __init__(self):
        self._agents: Dict[AgentName, BaseAgent] = {
            AgentName.FINOPS:      FinOpsAgent(),
            AgentName.ANOMALY:     AnomalyAgent(),
            AgentName.FORECASTING: ForecastingAgent(),
            AgentName.ADVISOR:     AdvisorAgent(),
            AgentName.CLOUDOPS:    CloudOpsAgent(),
            AgentName.SECURITY:    SecurityAgent(),
            AgentName.INCIDENT:    IncidentAgent(),
            AgentName.REMEDIATION: RemediationAgent(),
        }
        logger.info(f"AgentRouter initialised with {len(self._agents)} agents")

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_agent(self, name: AgentName) -> BaseAgent:
        return self._agents[name]

    def all_statuses(self) -> list:
        from datetime import datetime, timezone
        statuses = []
        for name, agent in self._agents.items():
            statuses.append({
                "name": name,
                "description": agent.description,
                "enabled": agent.enabled,
                "calls_today": agent.calls_today,
                "uptime_pct": agent.uptime_pct,
            })
        return statuses

    def toggle(self, name: AgentName, enabled: bool):
        self._agents[name].enabled = enabled

    async def dispatch(self, request: AgentChatRequest) -> AgentChatResponse:
        """
        Classify the user message, pick the best agent, and return its response.
        If the caller specifies an agent, use that directly.
        """
        agent_name = request.agent or self._classify(request.message)
        agent = self._agents[agent_name]

        if not agent.enabled:
            # Fall back to FinOps agent
            logger.warning(f"Agent {agent_name} disabled, falling back to FinOps")
            agent_name = AgentName.FINOPS
            agent = self._agents[agent_name]

        logger.info(f"Dispatching to {agent_name}: '{request.message[:60]}...'")

        result = await agent.run({
            "message": request.message,
            "history": request.conversation_history,
        })

        return AgentChatResponse(
            agent_used=agent_name,
            response=result.get("response", ""),
            actions_proposed=result.get("actions", []),
            sources=result.get("sources", []),
        )

    # ── Private ────────────────────────────────────────────────────────────────

    def _classify(self, message: str) -> AgentName:
        """
        Fast keyword-based classification.
        In production, replace/augment with a lightweight LLM classifier call.
        """
        lower = message.lower()
        scores: Dict[AgentName, int] = {n: 0 for n in AgentName}
        for keyword, agent_name in KEYWORD_MAP.items():
            if keyword in lower:
                scores[agent_name] += 1

        best = max(scores, key=lambda k: scores[k])
        if scores[best] == 0:
            # No keywords matched → default to FinOps (most general)
            logger.debug("No keyword match, defaulting to FinOps agent")
            return AgentName.FINOPS
        logger.debug(f"Classified as {best} (score={scores[best]})")
        return best


# ── Singleton instance (imported everywhere) ───────────────────────────────────
agent_router = AgentRouter()
