from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from config import settings

logger = logging.getLogger("finops.guardrails")

_STATE_PATH = Path(settings.FINOPS_STATE_FILE)
_DEFAULT_STATE: Dict[str, Any] = {
    "chat_mutations_enabled": True,
    "protected_resources": {},
    "spend_rules": {},
}
_state: Dict[str, Any] = {}


def _load_state() -> None:
    global _state
    try:
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            guardrails = data.get("guardrails", {})
            if isinstance(guardrails, dict):
                _state = {**_DEFAULT_STATE, **guardrails}
                _state.setdefault("protected_resources", {})
                _state.setdefault("spend_rules", {})
                return
    except Exception as exc:
        logger.warning("Could not load guardrail state from %s: %s", _STATE_PATH, exc)
    _state = {**_DEFAULT_STATE, "protected_resources": {}, "spend_rules": {}}


def _save_state() -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        data["guardrails"] = _state
        _STATE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist guardrail state to %s: %s", _STATE_PATH, exc)


_load_state()


def get_state() -> Dict[str, Any]:
    return {
        "chat_mutations_enabled": bool(_state.get("chat_mutations_enabled", True)),
        "protected_resources": list((_state.get("protected_resources") or {}).values()),
        "spend_rules": list((_state.get("spend_rules") or {}).values()),
    }


def set_chat_mutations_enabled(enabled: bool) -> Dict[str, Any]:
    _state["chat_mutations_enabled"] = bool(enabled)
    _state["updated_at"] = _now()
    _save_state()
    return get_state()


def protect_resource(resource: Dict[str, Any], protected_by: str = "web-ui") -> Dict[str, Any]:
    resource_id = _normalise_id(resource.get("id") or resource.get("resource_id") or "")
    if not resource_id:
        raise ValueError("resource id is required")
    blocked_actions = _normalise_actions(resource.get("blocked_actions") or resource.get("blocked_action") or ["all"])
    existing = (_state.get("protected_resources") or {}).get(resource_id) or {}
    existing_actions = _normalise_actions(existing.get("blocked_actions")) if existing else []
    if "all" in existing_actions or "all" in blocked_actions:
        blocked_actions = ["all"]
    else:
        blocked_actions = sorted(set(existing_actions + blocked_actions))
    item = {
        "id": resource_id,
        "name": resource.get("name") or resource_id.rstrip("/").split("/")[-1],
        "type": resource.get("type") or resource.get("raw_type") or "",
        "resource_group": resource.get("resource_group") or "",
        "region": resource.get("region") or "",
        "protected": True,
        "blocked_actions": blocked_actions,
        "protected_by": protected_by,
        "protected_at": _now(),
        "reason": resource.get("reason") or "Protected by FinOps.AI guardrail.",
    }
    _state.setdefault("protected_resources", {})[resource_id] = item
    _save_state()
    return item


def unprotect_resource(resource_id: str, client_id: str, client_secret: str) -> Dict[str, Any]:
    _verify_client_secret(client_id, client_secret)
    normalised = _normalise_id(resource_id)
    protected = _state.setdefault("protected_resources", {})
    item = protected.pop(normalised, None)
    if item is None:
        raise ValueError("resource is not protected")
    item["protected"] = False
    item["unprotected_at"] = _now()
    _save_state()
    return item


def is_resource_protected(resource_id_or_name: str, resource_name: str = "") -> Dict[str, Any] | None:
    protected = _state.get("protected_resources") or {}
    normalised = _normalise_id(resource_id_or_name)
    if normalised in protected:
        return protected[normalised]
    target_name = str(resource_name or resource_id_or_name or "").lower()
    for item in protected.values():
        if str(item.get("name") or "").lower() == target_name:
            return item
    return None


def is_action_blocked(action_type: str, resource_id_or_name: str, resource_name: str = "") -> Dict[str, Any] | None:
    protected = is_resource_protected(resource_id_or_name, resource_name)
    if not protected:
        return None
    blocked_actions = _normalise_actions(protected.get("blocked_actions") or ["all"])
    category = _action_category(action_type)
    raw = str(action_type or "").strip().lower()
    if "all" in blocked_actions or category in blocked_actions or raw in blocked_actions:
        return {**protected, "blocked_action": category}
    return None


def evaluate_action(action_type: str, resource: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    params = params or {}
    if _is_mutation(action_type) and not _state.get("chat_mutations_enabled", True):
        return _blocked("Chat-based mutation creation is disabled by guardrail. Turn it back on from Guardrails with the Azure client ID and secret.")

    protected = is_action_blocked(action_type, params.get("resource_id") or resource, params.get("resource_name") or resource)
    if protected and _is_mutation(action_type):
        name = protected.get("name") or resource
        action = protected.get("blocked_action") or _action_category(action_type)
        return _blocked(
            f"Resource '{name}' is protected by guardrail for '{action}' operations. Approval creation is blocked until that protection is turned off with the Azure client ID and secret.",
            protected,
        )
    return {"allowed": True, "reason": "Allowed by guardrails."}


def evaluate_execution(action_type: str, resource: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    protected = is_action_blocked(action_type, (params or {}).get("resource_id") or resource, (params or {}).get("resource_name") or resource)
    if protected and _is_mutation(action_type):
        action = protected.get("blocked_action") or _action_category(action_type)
        return _blocked(
            f"Execution blocked: resource '{protected.get('name')}' is protected by guardrail for '{action}' operations. Turn protection off only if this change is intentional.",
            protected,
        )
    return {"allowed": True, "reason": "Allowed by guardrails."}


def upsert_spend_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    resource_id = _normalise_id(rule.get("resource_id") or "")
    if not resource_id:
        raise ValueError("resource_id is required")
    threshold_amount = float(rule.get("threshold_amount") or 0)
    threshold_pct = float(rule.get("threshold_pct") or 0)
    if threshold_amount <= 0 and threshold_pct <= 0:
        raise ValueError("set threshold_amount or threshold_pct")
    rule_id = resource_id
    item = {
        "id": rule_id,
        "resource_id": resource_id,
        "resource_name": rule.get("resource_name") or resource_id.rstrip("/").split("/")[-1],
        "resource_group": rule.get("resource_group") or "",
        "resource_type": rule.get("resource_type") or "",
        "threshold_amount": threshold_amount,
        "threshold_pct": threshold_pct,
        "action": rule.get("action") or "stop_vm",
        "action_label": rule.get("action_label") or "",
        "enabled": bool(rule.get("enabled", True)),
        "created_at": rule.get("created_at") or _now(),
        "updated_at": _now(),
    }
    _state.setdefault("spend_rules", {})[rule_id] = item
    _save_state()
    return item


def delete_spend_rule(rule_id: str) -> Dict[str, Any]:
    rules = _state.setdefault("spend_rules", {})
    item = rules.pop(_normalise_id(rule_id), None)
    if item is None:
        raise ValueError("spend rule not found")
    _save_state()
    return item


def spend_rules() -> List[Dict[str, Any]]:
    return list((_state.get("spend_rules") or {}).values())


def _verify_client_secret(client_id: str, client_secret: str) -> None:
    if client_id != settings.AZURE_CLIENT_ID or client_secret != settings.AZURE_CLIENT_SECRET:
        raise PermissionError("Client ID or secret is incorrect. Guardrail protection remains enabled.")


def _blocked(reason: str, protected: Dict[str, Any] | None = None) -> Dict[str, Any]:
    result = {"allowed": False, "reason": reason, "status": "blocked_by_guardrail"}
    if protected:
        result["protected_resource"] = protected
    return result


def _is_mutation(action_type: str) -> bool:
    action = str(action_type or "").lower()
    return any(word in action for word in ["stop", "start", "restart", "resize", "scale", "delete", "create", "restore", "apply"])


def _normalise_actions(actions: Any) -> List[str]:
    if isinstance(actions, str):
        actions = [actions]
    if not isinstance(actions, list):
        actions = ["all"]
    normalised = []
    for action in actions:
        category = _action_category(str(action))
        if category not in normalised:
            normalised.append(category)
    return normalised or ["all"]


def _action_category(action_type: str) -> str:
    action = str(action_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if action in {"*", "all", "any"}:
        return "all"
    if "delete" in action or "remove" in action or "destroy" in action:
        return "delete"
    if "restart" in action or "reboot" in action:
        return "restart"
    if "resize" in action:
        return "resize"
    if "scale" in action:
        return "scale"
    if "stop" in action or "shutdown" in action or "deallocate" in action:
        return "stop"
    if "start" in action:
        return "start"
    if "create" in action:
        return "create"
    if "restore" in action:
        return "restore"
    if "apply" in action:
        return "apply"
    return action


def _normalise_id(value: str) -> str:
    return str(value or "").strip().rstrip("/").lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
