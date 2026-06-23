"""
/api/v1/approvals — Approval Queue: list, decide, execute.

Flow:
  Agents propose → approval_service stores → human approves →
  RemediationAgent.execute_approved_action() runs →
  audit_service records → logged.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from models.schemas import ApprovalDecision
from services import approval_service, audit_service
from services.approval_execution_service import decide_and_maybe_execute
from services.azure_account import AzureAccount, account_from_headers

router = APIRouter()


class ArchiveRequest(BaseModel):
    archived_by: str = "web-ui"
    reason: str = ""


@router.get("/audit/log")
async def audit_log(limit: int = 50):
    """Recent audit log entries."""
    return {
        "total":   audit_service.count(),
        "entries": audit_service.get_log(limit=limit),
    }


@router.get("/")
async def list_approvals(include_archived: bool = Query(False)):
    items = approval_service.list_all(include_archived=include_archived)
    return {
        "pending_count":               approval_service.pending_count(),
        "total_projected_savings_usd": approval_service.total_projected_savings_usd(),
        "items":                       items,
    }


@router.post("/{approval_id}/archive")
async def archive_approval(approval_id: str, body: ArchiveRequest):
    try:
        item = approval_service.archive(approval_id, archived_by=body.archived_by, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_service.record(
        event_type="archive",
        actor=body.archived_by,
        resource=item.get("resource", ""),
        action=item.get("action_type", item.get("action", "")),
        outcome="success",
        detail=body.reason,
        approval_id=approval_id,
    )
    return item


@router.get("/{approval_id}")
async def get_approval(approval_id: str):
    item = approval_service.get(approval_id)
    if not item:
        raise HTTPException(status_code=404, detail="Approval not found")
    return item


@router.post("/{approval_id}/decide")
async def decide(
    approval_id: str,
    body: ApprovalDecision,
    account: AzureAccount = Depends(account_from_headers),
):
    """Approve or reject an action. Approved actions are immediately executed."""
    try:
        result = await decide_and_maybe_execute(
            approval_id=approval_id,
            decision=body.decision,
            decided_by=body.approved_by,
            notes=body.notes or "",
            account=account,
        )
    except ValueError as e:
        status = 404 if "not found" in str(e) else 409
        raise HTTPException(status_code=status, detail=str(e))
    return result
