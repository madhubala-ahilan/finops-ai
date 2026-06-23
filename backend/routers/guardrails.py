from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List

from services import guardrail_service
from services.azure_account import AzureAccount, account_from_headers, reset_current_account, set_current_account

router = APIRouter()


class ChatMutationToggle(BaseModel):
    enabled: bool


class ProtectedResourceRequest(BaseModel):
    id: str
    name: str = ""
    type: str = ""
    raw_type: str = ""
    resource_group: str = ""
    region: str = ""
    reason: str = ""
    blocked_actions: List[str] = Field(default_factory=lambda: ["all"])
    protected_by: str = "web-ui"


class UnprotectRequest(BaseModel):
    resource_id: str
    client_id: str
    client_secret: str


class SpendRuleRequest(BaseModel):
    resource_id: str
    resource_name: str = ""
    resource_group: str = ""
    resource_type: str = ""
    threshold_amount: float = 0
    threshold_pct: float = 0
    action: str = "stop_vm"
    action_label: str = ""
    enabled: bool = True


@router.get("/")
async def list_guardrails():
    return guardrail_service.get_state()


@router.post("/chat-mutations")
async def set_chat_mutations(body: ChatMutationToggle):
    return guardrail_service.set_chat_mutations_enabled(body.enabled)


@router.post("/protect")
async def protect_resource(body: ProtectedResourceRequest):
    try:
        return guardrail_service.protect_resource(body.model_dump(), protected_by=body.protected_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/unprotect")
async def unprotect_resource(body: UnprotectRequest):
    try:
        return guardrail_service.unprotect_resource(body.resource_id, body.client_id, body.client_secret)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/spend-rules")
async def upsert_spend_rule(body: SpendRuleRequest):
    try:
        return guardrail_service.upsert_spend_rule(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/spend-rules/{rule_id:path}")
async def delete_spend_rule(rule_id: str):
    try:
        return guardrail_service.delete_spend_rule(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/evaluate-spend")
async def evaluate_spend_rules(account: AzureAccount = Depends(account_from_headers)):
    """Evaluate cost guardrails and run the selected supported action through the same remediation path."""
    token = set_current_account(account)
    try:
        from agents.remediation_agent import RemediationAgent
        from services.azure_cost_service import get_cost_analysis

        analysis = await get_cost_analysis(days=30, account=account)
        by_resource = {str(item.get("resource_id", "")).lower(): item for item in analysis.get("by_resource", [])}
        results: list[Dict[str, Any]] = []
        agent = RemediationAgent()
        for rule in guardrail_service.spend_rules():
            if not rule.get("enabled", True):
                continue
            resource_id = str(rule.get("resource_id", "")).lower()
            cost_row = by_resource.get(resource_id, {})
            amount = float(cost_row.get("amount") or 0)
            threshold_amount = float(rule.get("threshold_amount") or 0)
            pct_triggered = False
            amount_triggered = threshold_amount > 0 and amount >= threshold_amount
            if rule.get("threshold_pct"):
                total = float(analysis.get("total") or 0)
                pct_triggered = total > 0 and ((amount / total) * 100) >= float(rule["threshold_pct"])
            triggered = amount_triggered or pct_triggered
            result = {"rule": rule, "amount": amount, "triggered": triggered, "execution_result": None}
            if triggered:
                guard = guardrail_service.evaluate_execution(rule.get("action", "stop_vm"), rule.get("resource_id", ""), rule)
                if not guard.get("allowed"):
                    result["execution_result"] = guard
                else:
                    result["execution_result"] = await agent.execute_approved_action(
                        approval_id=f"guardrail-{rule.get('id')}",
                        action_type=rule.get("action", "stop_vm"),
                        resource=rule.get("resource_name") or rule.get("resource_id"),
                        params={"resource_id": rule.get("resource_id"), "resource_group": rule.get("resource_group")},
                        approved_by="guardrail-auto-action",
                    )
            results.append(result)
        return {"data_source": analysis.get("data_source"), "currency": analysis.get("currency"), "results": results}
    finally:
        reset_current_account(token)
