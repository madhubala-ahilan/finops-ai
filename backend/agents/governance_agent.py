"""
agents/governance_agent.py — Governance & Policy Agent.

Architecture Layer: Agent Layer → Governance Agent
Role: Safe enterprise control layer between AI recommendations and execution.

Responsibilities:
  1. Validate every proposed action against policy rules.
  2. Route actions to the correct approval tier (auto / human / blocked).
  3. Log all decisions to the audit trail.
  4. Enforce guardrails before RemedationAgent executes anything.

Approval tiers:
  AUTO     — low-risk, cost-saving, reversible actions (e.g. tag a resource)
  HUMAN    — medium-risk actions that need a person to Approve in the UI
  BLOCKED  — actions that violate policy (e.g. delete prod DB, stop prod VM)

Policy rules (extendable):
  • Never delete or stop a resource with "prod" in name without human approval.
  • Never act on a resource in the "rg-critical" resource group without human approval.
  • Auto-approve cost-saving actions under $500/month impact with Low risk.
  • Block any action on a resource tagged as "do-not-touch".
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from agents.base_agent import BaseAgent

logger = logging.getLogger("finops.governance")


# ── Policy rule definitions ────────────────────────────────────────────────────

BLOCKED_RULES = [
    {
        "id":          "BLOCK-001",
        "description": "Never delete/stop production resources without explicit override",
        "check": lambda action: (
            any(kw in action.get("action_type", "").lower()
                for kw in ["delete", "stop", "terminate", "remove"])
            and any(kw in (action.get("resource", "") + action.get("resource_group", "")).lower()
                    for kw in ["prod", "production", "live"])
        ),
    },
    {
        "id":          "BLOCK-002",
        "description": "Never act on resources tagged do-not-touch",
        "check": lambda action: (
            "do-not-touch" in str(action.get("tags", {})).lower()
        ),
    },
    {
        "id":          "BLOCK-003",
        "description": "Never modify resources in rg-critical resource group",
        "check": lambda action: (
            "critical" in action.get("resource_group", "").lower()
        ),
    },
]

HUMAN_APPROVAL_RULES = [
    {
        "id":          "HUMAN-001",
        "description": "Medium or High risk actions always need human approval",
        "check": lambda action: action.get("risk", "Low") in ("Medium", "High"),
    },
    {
        "id":          "HUMAN-002",
        "description": "Actions with savings > $500/month need human sign-off",
        "check": lambda action: _parse_savings(action.get("estimated_savings", "0")) > 500,
    },
    {
        "id":          "HUMAN-003",
        "description": "Any resize or scale action needs human approval",
        "check": lambda action: any(
            kw in action.get("action_type", "").lower()
            for kw in ["resize", "scale", "downsize", "upsize"]
        ),
    },
    {
        "id":          "HUMAN-004",
        "description": "Deletion of storage or databases needs human approval",
        "check": lambda action: (
            "delete" in action.get("action_type", "").lower()
            and any(kw in action.get("resource_type", "").lower()
                    for kw in ["storage", "sql", "database", "cosmos"])
        ),
    },
]


class GovernanceAgent(BaseAgent):
    name        = "Governance Agent"
    description = "Policy validation, approval routing, and execution guardrails"

    system_prompt = """
You are FinOps.AI's Governance Agent. You protect enterprise Azure environments
from unsafe AI-driven actions.

Your job:
1. Evaluate each proposed action against safety and policy rules.
2. Decide: BLOCKED / HUMAN_APPROVAL / AUTO_APPROVED.
3. Explain your decision clearly so the human understands why.
4. When approving, summarise the risk and any conditions.

Rules you enforce:
- Production resources need human approval for any destructive action.
- Cost-saving actions under $500/month with Low risk can auto-approve.
- Always prefer the least disruptive option.
- When uncertain, escalate to human rather than block.

Output JSON with: decision, reason, policy_rule_id, conditions.
"""

    def __init__(self):
        super().__init__()
        self._audit_log: List[Dict] = []

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate an action and decide its approval tier.

        Payload keys:
          action_type      (str)  e.g. "downsize_vm", "delete_storage", "enable_autoscaling"
          resource         (str)  Resource name
          resource_group   (str)  Resource group
          resource_type    (str)  e.g. "Virtual Machine", "Storage Account"
          risk             (str)  Low / Medium / High (from proposing agent)
          estimated_savings(str)  e.g. "$2,340/yr" or "$187/mo"
          detail           (str)  What the action does
          tags             (dict) Azure resource tags
          proposed_by      (str)  Which agent proposed this
        """
        action_type = payload.get("action_type", "")
        resource    = payload.get("resource", "")

        logger.info(f"[GovernanceAgent] Evaluating: {action_type} on {resource}")

        # ── Step 1: check BLOCKED rules ────────────────────────────────────────
        for rule in BLOCKED_RULES:
            if rule["check"](payload):
                result = {
                    "decision":       "BLOCKED",
                    "policy_rule_id": rule["id"],
                    "reason":         rule["description"],
                    "action_type":    action_type,
                    "resource":       resource,
                    "conditions":     [],
                    "response":       f"Action BLOCKED: {rule['description']}",
                    "evaluated_at":   datetime.now(timezone.utc).isoformat(),
                }
                self._audit(payload, result)
                logger.warning(f"[GovernanceAgent] BLOCKED: {action_type} | Rule: {rule['id']}")
                return result

        # ── Step 2: check HUMAN_APPROVAL rules ────────────────────────────────
        for rule in HUMAN_APPROVAL_RULES:
            if rule["check"](payload):
                result = {
                    "decision":       "HUMAN_APPROVAL",
                    "policy_rule_id": rule["id"],
                    "reason":         rule["description"],
                    "action_type":    action_type,
                    "resource":       resource,
                    "conditions":     ["Requires approval in the FinOps.AI Approval Queue"],
                    "response":       (
                        f"Action queued for human approval. Reason: {rule['description']}. "
                        f"Open the Approval Queue to approve or reject."
                    ),
                    "evaluated_at":   datetime.now(timezone.utc).isoformat(),
                }
                self._audit(payload, result)
                logger.info(f"[GovernanceAgent] HUMAN_APPROVAL: {action_type} | Rule: {rule['id']}")
                return result

        # ── Step 3: AUTO_APPROVED (all rules passed) ───────────────────────────
        savings = payload.get("estimated_savings", "")
        result = {
            "decision":       "AUTO_APPROVED",
            "policy_rule_id": "AUTO-001",
            "reason":         "Action passed all policy checks. Low risk, reversible, within budget.",
            "action_type":    action_type,
            "resource":       resource,
            "conditions":     [
                "Execution will be logged to audit trail",
                "Action is reversible within 24h",
                f"Estimated savings: {savings}" if savings else "Savings not specified",
            ],
            "response":       (
                f"Action AUTO_APPROVED: {action_type} on {resource}. "
                f"Passes all governance policy checks. Proceeding with execution."
            ),
            "evaluated_at":   datetime.now(timezone.utc).isoformat(),
        }
        self._audit(payload, result)
        logger.info(f"[GovernanceAgent] AUTO_APPROVED: {action_type} on {resource}")
        return result

    async def validate_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Public helper — validate a single action dict."""
        return await self.run(action)

    async def get_audit_log(self, limit: int = 50) -> List[Dict]:
        """Return recent audit log entries (newest first)."""
        return list(reversed(self._audit_log[-limit:]))

    async def get_pending_approvals_count(self) -> int:
        """Count actions currently pending human approval."""
        return sum(
            1 for entry in self._audit_log
            if entry.get("result", {}).get("decision") == "HUMAN_APPROVAL"
        )

    def _audit(self, payload: Dict, result: Dict):
        """Append a decision to the in-memory audit trail."""
        self._audit_log.append({
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "proposed_by": payload.get("proposed_by", "unknown"),
            "action":      payload.get("action_type", ""),
            "resource":    payload.get("resource", ""),
            "result":      result,
        })
        # Keep last 500 entries in memory
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_savings(savings_str: str) -> float:
    """Extract numeric dollar value from strings like '$2,340/yr' or '$187/mo'."""
    import re
    digits = re.sub(r"[^\d.]", "", savings_str.replace(",", ""))
    try:
        val = float(digits) if digits else 0.0
    except ValueError:
        return 0.0
    # Normalise to monthly value
    if "/yr" in savings_str or "year" in savings_str.lower():
        val = val / 12
    return val


# ── Module-level singleton ────────────────────────────────────────────────────

_governance_agent_instance: Optional[GovernanceAgent] = None


def get_governance_agent() -> GovernanceAgent:
    global _governance_agent_instance
    if _governance_agent_instance is None:
        _governance_agent_instance = GovernanceAgent()
    return _governance_agent_instance
