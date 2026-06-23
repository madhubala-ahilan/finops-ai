"""
services/audit_service.py
Immutable audit log for all governance actions.

Records:
  - Approval / rejection decisions
  - Agent-executed remediations
  - Policy violations
  - Manual override events

Architecture: in-memory for development.
Production: Azure SQL `audit_logs` table (append-only, no UPDATE/DELETE).
"""

from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import settings

logger = logging.getLogger("finops.audit")


# ── Append-only log ───────────────────────────────────────────────────────────

_STATE_PATH = Path(settings.FINOPS_STATE_FILE)
_log: List[Dict[str, Any]] = []


def _load_log() -> None:
    global _log
    try:
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            audit = data.get("audit_log", [])
            if isinstance(audit, list):
                _log = audit
    except Exception as exc:
        logger.warning("Could not load audit state from %s: %s", _STATE_PATH, exc)


def _save_log() -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        data["audit_log"] = _log[-2000:]
        _STATE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist audit state to %s: %s", _STATE_PATH, exc)


_load_log()


def record(
    event_type: str,
    actor: str,
    resource: str,
    action: str,
    outcome: str,
    detail: str = "",
    approval_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Append an audit entry. All parameters are required except detail/approval_id/metadata.

    Args:
        event_type:   "approval", "rejection", "execution", "policy_violation", "override"
        actor:        Who triggered it — agent name or user email
        resource:     Azure resource ID or name
        action:       What was done — "vm_downsize", "delete_storage", etc.
        outcome:      "success" | "failed" | "skipped"
        detail:       Free-text detail
        approval_id:  Linked approval queue ID, if applicable
        metadata:     Arbitrary extra context dict
    """
    entry: Dict[str, Any] = {
        "id":           str(uuid.uuid4()),
        "event_type":   event_type,
        "actor":        actor,
        "resource":     resource,
        "action":       action,
        "outcome":      outcome,
        "detail":       detail,
        "approval_id":  approval_id,
        "metadata":     metadata or {},
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }
    _log.append(entry)
    _save_log()
    logger.info(
        "AUDIT [%s] %s → %s on %s | outcome=%s",
        event_type, actor, action, resource, outcome,
    )
    return entry


def get_log(
    event_type: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Return recent audit entries, newest first.
    Optionally filter by event_type or actor.
    """
    entries = list(reversed(_log))
    if event_type:
        entries = [e for e in entries if e["event_type"] == event_type]
    if actor:
        entries = [e for e in entries if e["actor"] == actor]
    return entries[:limit]


def count() -> int:
    return len(_log)
