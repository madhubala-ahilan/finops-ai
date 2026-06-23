from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger("finops.approvals")

_STATE_PATH = Path(settings.FINOPS_STATE_FILE)
_store: Dict[str, Dict[str, Any]] = {}


def _load_store() -> None:
    global _store
    try:
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            approvals = data.get("approvals", {})
            if isinstance(approvals, dict):
                _store = approvals
    except Exception as exc:
        logger.warning("Could not load approval state from %s: %s", _STATE_PATH, exc)


def _save_store() -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        data["approvals"] = _store
        _STATE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist approval state to %s: %s", _STATE_PATH, exc)


_load_store()


def list_all(include_archived: bool = False) -> List[Dict[str, Any]]:
    items = list(_store.values())
    if not include_archived:
        items = [item for item in items if not item.get("archived")]
    return items


def get(approval_id: str) -> Optional[Dict[str, Any]]:
    return _store.get(approval_id)


def pending_count() -> int:
    return sum(1 for item in _store.values() if item["status"] == "pending" and not item.get("archived"))


def total_projected_savings_usd() -> float:
    total = 0.0
    for item in _store.values():
        if item["status"] != "pending" or item.get("archived"):
            continue
        raw = str(item.get("projected_savings", ""))
        match = re.search(r"[\d,]+", raw.replace(",", ""))
        if match:
            value = float(match.group().replace(",", ""))
            if "/mo" in raw:
                value *= 12
            total += value
    return round(total, 2)


def create(item: Dict[str, Any]) -> Dict[str, Any]:
    _store[item["id"]] = item
    _save_store()
    logger.info("Approval created: %s - %s on %s", item["id"], item.get("action"), item.get("resource"))
    return item


async def create_approval_request(
    action_type: str,
    resource_id: str,
    justification: str,
    estimated_savings: float = 0.0,
    risk: str = "Medium",
    params: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    from services import guardrail_service

    guard = guardrail_service.evaluate_action(action_type, resource_id, params or {})
    if not guard.get("allowed", True):
        raise ValueError(guard.get("reason", "Blocked by guardrail."))

    approval_id = f"apr-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    return create({
        "id": approval_id,
        "agent": "AI Agent",
        "action": action_type.replace("_", " ").title(),
        "action_type": action_type,
        "resource": resource_id,
        "detail": justification,
        "justification": justification,
        "risk": risk,
        "params": params or {},
        "projected_savings": f"${estimated_savings:.2f}/mo" if estimated_savings else "",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def get_pending_approvals() -> List[Dict[str, Any]]:
    return [item for item in list_all() if item.get("status") == "pending"]


def archive(approval_id: str, archived_by: str = "web-ui", reason: str = "") -> Dict[str, Any]:
    item = _store.get(approval_id)
    if item is None:
        raise ValueError(f"Approval '{approval_id}' not found")
    item["archived"] = True
    item["archived_at"] = datetime.now(timezone.utc).isoformat()
    item["archived_by"] = archived_by
    item["archive_reason"] = reason
    _save_store()
    logger.info("Approval %s archived by %s", approval_id, archived_by)
    return item


def decide(
    approval_id: str,
    decision: str,
    decided_by: str,
    notes: str = "",
) -> Dict[str, Any]:
    item = _store.get(approval_id)
    if item is None:
        raise ValueError(f"Approval '{approval_id}' not found")
    if item["status"] != "pending":
        raise ValueError(f"Approval '{approval_id}' is already '{item['status']}'")

    item["status"] = decision
    item["decided_at"] = datetime.now(timezone.utc).isoformat()
    item["decided_by"] = decided_by
    item["notes"] = notes

    _save_store()
    logger.info("Approval %s: %s by %s", approval_id, decision.upper(), decided_by)
    return item


def record_execution_attempt(
    approval_id: str,
    execution_result: Dict[str, Any],
    attempted_by: str,
) -> Dict[str, Any]:
    item = _store.get(approval_id)
    if item is None:
        raise ValueError(f"Approval '{approval_id}' not found")

    attempt = {
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "attempted_by": attempted_by,
        "result": execution_result,
    }
    attempts = item.setdefault("execution_attempts", [])
    attempts.append(attempt)
    item["last_execution_result"] = execution_result
    item["last_execution_status"] = execution_result.get("status") or (
        "success" if execution_result.get("success") else "failed"
    )
    item["last_attempted_at"] = attempt["attempted_at"]
    item["last_attempted_by"] = attempted_by
    _save_store()
    logger.info(
        "Approval %s execution attempt by %s: %s",
        approval_id,
        attempted_by,
        item["last_execution_status"],
    )
    return item


def execution_succeeded(execution_result: Dict[str, Any] | None) -> bool:
    if not isinstance(execution_result, dict):
        return False
    status = str(execution_result.get("status") or "").lower()
    if execution_result.get("success") is True:
        return True
    return status in {"success", "succeeded", "completed", "accepted", "started", "restarted", "deallocated"}
