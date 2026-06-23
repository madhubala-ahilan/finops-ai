from __future__ import annotations

import logging
from typing import Any, Dict

from models.schemas import AgentName
from agents.router import agent_router
from services import approval_service, audit_service
from services.azure_account import AzureAccount, reset_current_account, set_current_account

logger = logging.getLogger("finops.approval_execution")


async def decide_and_maybe_execute(
    approval_id: str,
    decision: str,
    decided_by: str,
    notes: str = "",
    account: AzureAccount | None = None,
) -> Dict[str, Any]:
    item = approval_service.get(approval_id)
    if item is None:
        raise ValueError(f"Approval '{approval_id}' not found")
    if item.get("status") != "pending":
        raise ValueError(f"Approval '{approval_id}' is already '{item.get('status')}'")

    if decision == "rejected":
        item = approval_service.decide(approval_id, decision, decided_by=decided_by, notes=notes)
        audit_service.record(
            event_type="rejection",
            actor=decided_by,
            resource=item.get("resource", ""),
            action=item.get("action_type", item.get("action", "")),
            outcome="success",
            detail=notes,
            approval_id=approval_id,
        )
        return {
            "approval_id": approval_id,
            "status": item["status"],
            "decided_by": decided_by,
            "approval": item,
            "execution_result": None,
            "execution_succeeded": None,
        }

    from services import guardrail_service

    guard = guardrail_service.evaluate_execution(
        item.get("action_type", ""),
        item.get("resource", ""),
        item.get("params", {}),
    )
    if not guard.get("allowed", True):
        item = approval_service.decide(
            approval_id,
            "rejected",
            decided_by="guardrail",
            notes=guard.get("reason", "Rejected by guardrail."),
        )
        execution_result = {
            "status": "blocked_by_guardrail",
            "success": False,
            "error": guard.get("reason", "Rejected by guardrail."),
            "guardrail": guard,
        }
        audit_service.record(
            event_type="approval",
            actor=decided_by,
            resource=item.get("resource", ""),
            action=item.get("action_type", item.get("action", "")),
            outcome="blocked",
            detail=execution_result["error"],
            approval_id=approval_id,
        )
        return {
            "approval_id": approval_id,
            "status": item["status"],
            "decided_by": "guardrail",
            "approval": item,
            "execution_result": execution_result,
            "execution_succeeded": False,
        }

    execution_result: Dict[str, Any]
    token = set_current_account(account) if account is not None else None
    try:
        remediation_agent = agent_router.get_agent(AgentName.REMEDIATION)
        execution_result = await remediation_agent.execute_approved_action(
            approval_id=approval_id,
            action_type=item.get("action_type", ""),
            resource=item.get("resource", ""),
            params=item.get("params", {}),
            approved_by=decided_by,
        )
    except Exception as exc:
        logger.exception("Approval %s execution raised", approval_id)
        execution_result = {"status": "failed", "success": False, "error": str(exc)}
    finally:
        if token is not None:
            reset_current_account(token)

    success = approval_service.execution_succeeded(execution_result)
    if success:
        item = approval_service.decide(approval_id, "approved", decided_by=decided_by, notes=notes)
    else:
        item = approval_service.record_execution_attempt(approval_id, execution_result, attempted_by=decided_by)

    audit_detail = notes
    if isinstance(execution_result, dict):
        audit_detail = (
            execution_result.get("error")
            or execution_result.get("note")
            or execution_result.get("message")
            or notes
        )

    audit_service.record(
        event_type="approval",
        actor=decided_by,
        resource=item.get("resource", ""),
        action=item.get("action_type", item.get("action", "")),
        outcome="success" if success else "failed",
        detail=audit_detail,
        approval_id=approval_id,
    )

    return {
        "approval_id": approval_id,
        "status": item["status"],
        "decided_by": decided_by,
        "approval": item,
        "execution_result": execution_result,
        "execution_succeeded": success,
    }
