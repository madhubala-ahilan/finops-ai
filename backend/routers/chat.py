"""
routers/chat.py — AI Chat endpoint backed by LangGraph multi-agent system.
POST /api/v1/chat  →  runs the LangGraph supervisor + specialist agents
GET  /api/v1/chat/agents  →  lists available agents
"""

import logging
import re
import traceback

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from config import settings
from services.azure_account import (
    AzureAccount,
    account_from_headers,
    reset_current_account,
    set_current_account,
)

router = APIRouter()
logger = logging.getLogger("finops.chat")
_OPENAI_DISABLED_REASON: str | None = None


def _openai_config_snapshot() -> dict:
    endpoint = settings.AZURE_OPENAI_ENDPOINT or ""
    return {
        "endpoint": endpoint,
        "endpoint_host": endpoint.replace("https://", "").split("/")[0] if endpoint else "",
        "endpoint_family": settings.openai_endpoint_family(),
        "openai_v1_base_url": settings.openai_v1_base_url() if endpoint else "",
        "deployment": settings.AZURE_OPENAI_DEPLOYMENT,
        "api_version": settings.AZURE_OPENAI_API_VERSION,
        "key_configured": bool(settings.AZURE_OPENAI_KEY),
        "endpoint_looks_like_azure_openai": ".openai.azure.com" in endpoint.lower(),
    }


def _log_openai_exception(stage: str, exc: Exception | str) -> None:
    logger.error(
        "Azure OpenAI failure at %s | config=%s | error=%s",
        stage,
        _openai_config_snapshot(),
        exc,
    )
    if isinstance(exc, Exception):
        logger.error("Azure OpenAI traceback at %s:\n%s", stage, traceback.format_exc())


def _exception_payload(exc: Exception) -> dict:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "status_code": getattr(exc, "status_code", None),
        "code": getattr(exc, "code", None),
        "request_id": getattr(exc, "request_id", None),
        "body": getattr(exc, "body", None),
    }


def _cost_note_for_user(summary: dict) -> str:
    note = summary.get("note") or ""
    if summary.get("mtd_spend", 0) and "throttl" in note.lower():
        return "Showing cached live Azure cost data while Azure refreshes billing API availability."
    return note


def _openai_unavailable_reason() -> str | None:
    issue = settings.azure_openai_configuration_issue()
    if issue == "Azure OpenAI is not configured.":
        return "Azure OpenAI is not configured, so direct ChatOps tools are active."
    if issue:
        return f"{issue} Direct ChatOps tools are active."
    return None


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    agent: Optional[str] = None   # force a specific agent, otherwise supervisor routes


class ChatResponse(BaseModel):
    response: str
    agent_used: str
    tool_results: list[dict] = []
    actions_proposed: list[dict] = []
    error: Optional[str] = None


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, account: AzureAccount = Depends(account_from_headers)):
    """
    Send a message to the FinOps AI multi-agent system.
    The supervisor automatically routes to the best specialist agent.
    """
    global _OPENAI_DISABLED_REASON
    try:
        token = set_current_account(account)
        configured_issue = _openai_unavailable_reason()
        if configured_issue:
            fallback = await _chatops_without_llm(req.message, account)
            fallback["error"] = configured_issue
            return ChatResponse(**fallback)
        from agents.langgraph_orchestrator import run_agent
        result = await run_agent(
            message=req.message,
            history=req.history,
            agent_override=req.agent,
        )
        if result.get("error"):
            _log_openai_exception("langgraph_result_error", result.get("error", "unknown error"))
            if "404" in result.get("error", "") or "resource not found" in result.get("error", "").lower():
                _OPENAI_DISABLED_REASON = result.get("error")
            fallback = await _chatops_without_llm(req.message, account)
            fallback["error"] = result.get("error")
            fallback["response"] = (
                "Azure OpenAI returned an error, so I used direct ChatOps tools instead.\n\n"
                f"{fallback['response']}"
            )
            return ChatResponse(**fallback)
        return ChatResponse(**result)
    except Exception as exc:
        _log_openai_exception("chat_endpoint_exception", exc)
        if "404" in str(exc) or "resource not found" in str(exc).lower():
            _OPENAI_DISABLED_REASON = str(exc)
        fallback = await _chatops_without_llm(req.message, account)
        fallback["error"] = str(exc)
        fallback["response"] = (
            "The LangGraph chat path failed, so I ran the live Azure tools directly.\n\n"
            f"{fallback['response']}"
        )
        return ChatResponse(**fallback)
    finally:
        if "token" in locals():
            reset_current_account(token)


@router.get("/debug/openai")
async def debug_openai():
    """Return Azure OpenAI configuration and run a tiny completion probe."""
    config = _openai_config_snapshot()
    unavailable = _openai_unavailable_reason()
    payload = {
        "config": config,
        "disabled_reason": _OPENAI_DISABLED_REASON,
        "configuration_issue": unavailable,
        "probe_ok": False,
        "probe_error": None,
    }
    if unavailable:
        return payload

    try:
        from integrations.azure.openai_client import get_client

        client = get_client()
        response = await client.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "Reply with exactly: ok"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=5,
            temperature=0,
        )
        payload["probe_ok"] = True
        payload["probe_response"] = response.choices[0].message.content
        return payload
    except Exception as exc:
        _log_openai_exception("debug_openai_probe", exc)
        payload["probe_error"] = _exception_payload(exc)
        return payload


@router.post("/debug/openai/reset")
async def reset_openai_error():
    global _OPENAI_DISABLED_REASON
    previous = _OPENAI_DISABLED_REASON
    _OPENAI_DISABLED_REASON = None
    return {"reset": True, "previous_disabled_reason": previous}


async def _chatops_without_llm(message: str, account: AzureAccount) -> dict:
    msg = message.lower()
    if any(word in msg for word in ["approve", "approved", "reject", "rejected"]) and "apr-" in msg:
        return await _handle_approval_decision(message)

    if "approval" in msg or "pending" in msg:
        from services import approval_service

        items = await approval_service.get_pending_approvals()
        if not items:
            response = "There are no pending approvals right now."
        else:
            response = "Pending approvals:\n" + "\n".join(
                f"- {item['id']}: {item['action']} on {item['resource']} ({item['risk']} risk)"
                for item in items
            )
        return {
            "response": response,
            "agent_used": "approval_agent",
            "tool_results": [{"tool": "list_pending_approvals", "result": {"items": items, "total": len(items)}}],
            "actions_proposed": [],
            "error": None,
        }

    operation = await _maybe_create_operation_approval(message)
    if operation:
        return operation

    if "check blob" in msg or "blob exists" in msg or "find blob" in msg:
        return await _handle_blob_check(message)

    if any(word in msg for word in ["blob", "container", "storage account", "storage"]):
        return await _handle_storage_query(account)

    if any(word in msg for word in ["security", "defender", "policy", "compliance", "vulnerability", "secure"]):
        from agents.security_agent import get_security_posture
        from services.azure_policy_service import get_policy_compliance_summary

        posture = await get_security_posture()
        policy = posture.get("policy") or await get_policy_compliance_summary()
        findings = posture.get("findings", [])[:5]
        response = (
            "I ran live Azure security posture tools directly.\n"
            f"Security findings returned: {posture.get('total', 0)}.\n"
            f"Policy non-compliant resources returned: {policy.get('total_non_compliant', 0)}.\n"
            f"Data source: {posture.get('data_source', 'unknown')}."
        )
        if posture.get("note"):
            response += f"\n{posture['note']}"
        if findings:
            response += "\n\nFindings:\n" + "\n".join(
                f"- {item.get('name') or item.get('id')} ({item.get('type')})"
                for item in findings
            )
        return {
            "response": response,
            "agent_used": "security_agent",
            "tool_results": [
                {"tool": "get_security_posture", "result": posture},
                {"tool": "get_policy_compliance", "result": policy},
            ],
            "actions_proposed": [],
            "error": None,
        }

    if any(word in msg for word in ["resource", "vm", "inventory", "health", "advisor", "recommend"]):
        from services.azure_resource_service import get_advisor_recommendations, get_all_resources

        resources = await get_all_resources(account)
        recs = await get_advisor_recommendations(account)
        resource_lines = [
            f"- {r.get('name')} ({r.get('type')}) in {r.get('resource_group')}"
            for r in resources.get("resources", [])[:8]
        ]
        rec_lines = [
            f"- {r.get('short_description') or r.get('problem') or 'Advisor recommendation'}"
            for r in recs[:5]
        ]
        response = (
            "I ran live CloudOps tools directly.\n"
            f"Resources returned: {resources.get('total', 0)}.\n"
            f"Advisor recommendations returned: {len(recs)}."
        )
        if resource_lines:
            response += "\n\nResources:\n" + "\n".join(resource_lines)
        if rec_lines:
            response += "\n\nRecommendations:\n" + "\n".join(rec_lines)
        return {
            "response": response,
            "agent_used": "cloudops_agent",
            "tool_results": [
                {"tool": "list_resources", "result": resources},
                {"tool": "get_advisor_recommendations", "result": {"total": len(recs), "recommendations": recs}},
            ],
            "actions_proposed": [],
            "error": None,
        }

    from services.azure_cost_service import get_cost_by_service, get_mtd_summary

    summary = await get_mtd_summary(account)
    services = await get_cost_by_service(account=account)
    response = (
        "I ran live FinOps tools directly.\n"
        f"Month-to-date spend: {summary.get('currency', 'USD')} {summary.get('mtd_spend', 0)}.\n"
        f"Budget utilization: {summary.get('budget_utilisation_pct', 0)}%.\n"
        f"Cost data source: {summary.get('data_source', 'unknown')}."
    )
    top_services = services.get("services", [])[:5]
    if top_services:
        response += "\n\nTop services:\n" + "\n".join(
            f"- {svc.get('name')}: {summary.get('currency', 'USD')} {svc.get('amount', 0)}"
            for svc in top_services
        )
    note = _cost_note_for_user(summary)
    if note:
        response += f"\n{note}"
    return {
        "response": response,
        "agent_used": "finops_agent",
        "tool_results": [
            {"tool": "get_cost_summary", "result": summary},
            {"tool": "get_cost_by_service", "result": services},
        ],
        "actions_proposed": [],
        "error": None,
    }


async def _handle_storage_query(account: AzureAccount) -> dict:
    from services.azure_resource_service import get_all_resources

    resources = await get_all_resources(account)
    storage_accounts = [
        item for item in resources.get("resources", [])
        if "microsoft.storage/storageaccounts" in str(item.get("raw_type") or item.get("type") or "").lower()
    ]

    inspected: list[dict] = []
    for storage in storage_accounts[:5]:
        account_name = storage.get("name")
        entry = {
            "storage_account": account_name,
            "resource_group": storage.get("resource_group"),
            "containers": [],
            "error": None,
        }
        try:
            from azure.storage.blob import BlobServiceClient

            client = BlobServiceClient(
                account_url=f"https://{account_name}.blob.core.windows.net",
                credential=account.credential(),
            )
            for container in client.list_containers(results_per_page=10):
                container_name = container.get("name") if isinstance(container, dict) else getattr(container, "name", "")
                blobs = []
                try:
                    blob_client = client.get_container_client(container_name)
                    for blob in blob_client.list_blobs(results_per_page=5):
                        blobs.append(blob.get("name") if isinstance(blob, dict) else getattr(blob, "name", ""))
                        if len(blobs) >= 5:
                            break
                except Exception as blob_exc:
                    blobs.append(f"Could not list blobs: {type(blob_exc).__name__}: {blob_exc}")
                entry["containers"].append({"name": container_name, "sample_blobs": blobs})
                if len(entry["containers"]) >= 5:
                    break
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        inspected.append(entry)

    if not storage_accounts:
        response = "I checked live Azure Resource Graph and did not find storage accounts in this subscription."
    else:
        response = f"I found {len(storage_accounts)} storage account(s)."
        for item in inspected:
            response += f"\n- {item['storage_account']} in {item.get('resource_group') or 'unknown rg'}"
            if item["error"]:
                response += f" | blob listing error: {item['error']}"
            elif item["containers"]:
                response += f" | containers: {len(item['containers'])}"
                for container in item["containers"][:3]:
                    blob_sample = ", ".join([blob for blob in container.get("sample_blobs", []) if blob][:3]) or "no blobs returned"
                    response += f"\n  - {container['name']}: {blob_sample}"
            else:
                response += " | no containers returned"

    return {
        "response": response,
        "agent_used": "cloudops_agent",
        "tool_results": [
            {"tool": "get_storage_accounts", "result": {"total": len(storage_accounts), "items": storage_accounts}},
            {"tool": "list_blob_containers", "result": {"items": inspected}},
        ],
        "actions_proposed": [],
        "error": None,
    }


async def _handle_blob_check(message: str) -> dict:
    text = message.strip()
    blob_match = re.search(r"(?:check|find)\s+blob\s+([A-Za-z0-9_.()/\-]+)", text, re.IGNORECASE)
    storage_match = re.search(r"storage_account\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
    container_match = re.search(r"\bcontainer\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
    blob_path = blob_match.group(1) if blob_match else ""
    container_name = container_match.group(1) if container_match else ""
    blob_name = blob_path
    if not container_name and "/" in blob_path:
        container_name, blob_name = blob_path.split("/", 1)

    if not all([storage_match, container_name, blob_name]):
        return _chat_error(
            "I need storage account, container, and blob path. Example: check blob assets/logo.png storage_account mystorage.",
            agent="cloudops_agent",
        )

    from mcp_layer.cloudops_server.tools import check_blob_asset

    result = await check_blob_asset(
        storage_account=storage_match.group(1),
        container_name=container_name,
        blob_name=blob_name,
    )
    if result.get("exists") is True:
        response = (
            f"Blob exists: {container_name}/{blob_name}\n"
            f"Storage account: {storage_match.group(1)}\n"
            f"Size: {result.get('size_bytes', 0)} bytes\n"
            f"Last modified: {result.get('last_modified', 'unknown')}"
        )
    elif result.get("exists") is False:
        response = (
            f"Blob was not found: {container_name}/{blob_name}\n"
            f"Storage account: {storage_match.group(1)}\n"
            f"{result.get('recommended_action') or result.get('error') or ''}"
        )
    else:
        response = f"Could not check blob {container_name}/{blob_name}: {result.get('error', 'unknown error')}"

    return {
        "response": response,
        "agent_used": "cloudops_agent",
        "tool_results": [{"tool": "check_blob_asset", "result": result}],
        "actions_proposed": [],
        "error": None,
    }


async def _handle_approval_decision(message: str) -> dict:
    from services.approval_execution_service import decide_and_maybe_execute

    match = re.search(r"apr-\d+", message, re.IGNORECASE)
    if not match:
        return _chat_error("I could not find an approval ID. Use a message like: approve apr-20260529010101000000.")

    approval_id = match.group(0)
    decision = "rejected" if "reject" in message.lower() else "approved"
    try:
        result = await decide_and_maybe_execute(
            approval_id=approval_id,
            decision=decision,
            decided_by="chatbot",
            notes="Decided from chatbot",
        )
    except ValueError as exc:
        return _chat_error(str(exc), agent="approval_agent")

    execution_result = result.get("execution_result")
    if decision == "approved" and result.get("execution_succeeded") is False:
        response = f"{approval_id} could not execute yet, so it is still pending."
    else:
        response = f"{approval_id} was {decision}."
    if execution_result:
        status = execution_result.get("status") or ("success" if execution_result.get("success") else "failed")
        response += f"\nExecution status: {status}."
        if execution_result.get("error"):
            response += f"\nError: {execution_result['error']}"
        elif execution_result.get("note"):
            response += f"\nNote: {execution_result['note']}"

    return {
        "response": response,
        "agent_used": "approval_agent",
        "tool_results": [{"tool": "decide_approval", "result": result}],
        "actions_proposed": [],
        "error": None,
    }


async def _maybe_create_operation_approval(message: str) -> dict | None:
    from services.approval_service import create_approval_request

    text = message.strip()
    msg = text.lower()
    action_type = ""
    resource = ""
    params: dict = {}
    risk = "Medium"
    justification = "Requested from chatbot. Execution requires explicit approval."

    rg_match = re.search(r"(?:resource group|rg)\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
    if rg_match:
        params["resource_group"] = rg_match.group(1)
    resource_id_match = re.search(r"\bresource_id\s+(\S+)", text, re.IGNORECASE)
    if resource_id_match:
        params["resource_id"] = resource_id_match.group(1)
    location_match = re.search(r"\b(?:region|location)\s+([A-Za-z0-9_\-]+)", text, re.IGNORECASE)
    if location_match:
        params["location"] = location_match.group(1)

    if any(word in msg for word in ["stop vm", "deallocate vm", "shutdown vm", "shut down vm"]):
        action_type = "stop_vm"
        vm_match = re.search(r"(?:stop|deallocate|shutdown|shut down)\s+vm\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = vm_match.group(1) if vm_match else ""
        risk = "Medium"
    elif "start vm" in msg:
        action_type = "start_vm"
        vm_match = re.search(r"start\s+vm\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = vm_match.group(1) if vm_match else ""
        risk = "Low"
    elif "restart vm" in msg or "reboot vm" in msg:
        action_type = "restart_vm"
        vm_match = re.search(r"(?:restart|reboot)\s+vm\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = vm_match.group(1) if vm_match else ""
        risk = "Low"
    elif "resize vm" in msg:
        action_type = "resize_vm"
        vm_match = re.search(r"resize\s+vm\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        sku_match = re.search(r"\bto\s+([A-Za-z0-9_]+(?:_[A-Za-z0-9]+)*)", text, re.IGNORECASE)
        resource = vm_match.group(1) if vm_match else ""
        if sku_match:
            params["target_sku"] = sku_match.group(1)
    elif "restart app" in msg or "restart app service" in msg:
        action_type = "restart_app_service"
        app_match = re.search(r"restart\s+(?:app service|app)\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = app_match.group(1) if app_match else ""
        risk = "Low"
    elif "stop app" in msg or "stop app service" in msg:
        action_type = "stop_app_service"
        app_match = re.search(r"stop\s+(?:app service|app)\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = app_match.group(1) if app_match else ""
        risk = "Medium"
    elif "start app" in msg or "start app service" in msg:
        action_type = "start_app_service"
        app_match = re.search(r"start\s+(?:app service|app)\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = app_match.group(1) if app_match else ""
        risk = "Low"
    elif "scale container app" in msg or "scale containerapp" in msg:
        action_type = "scale_container_app"
        app_match = re.search(r"scale\s+container\s*app\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = app_match.group(1) if app_match else ""
        min_match = re.search(r"\bmin\s+(\d+)", text, re.IGNORECASE)
        max_match = re.search(r"\bmax\s+(\d+)", text, re.IGNORECASE)
        to_match = re.search(r"\bto\s+(\d+)", text, re.IGNORECASE)
        if min_match:
            params["min_replicas"] = int(min_match.group(1))
        if max_match:
            params["max_replicas"] = int(max_match.group(1))
        if to_match and not (min_match or max_match):
            params["min_replicas"] = int(to_match.group(1))
            params["max_replicas"] = int(to_match.group(1))
        risk = "Medium"
    elif "restore blob" in msg:
        action_type = "restore_blob"
        blob_match = re.search(r"restore\s+blob\s+([A-Za-z0-9_.()/\-]+)", text, re.IGNORECASE)
        resource = blob_match.group(1) if blob_match else "blob"
        for key in ["container", "storage_account", "backup_source"]:
            match = re.search(fr"{key}\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
            if match:
                params[key] = match.group(1)
        blob_name = resource
        if "container" not in params and "/" in resource:
            params["container_name"], blob_name = resource.split("/", 1)
        elif "container" in params:
            params["container_name"] = params.pop("container")
        params.setdefault("blob_name", blob_name)
    elif "delete resource" in msg or "delete azure resource" in msg:
        action_type = "delete_resource"
        delete_match = re.search(r"delete\s+(?:azure\s+)?resource\s+(.+?)(?:\s+resource_id\s+|\s+rg\s+|\s+resource group\s+|$)", text, re.IGNORECASE)
        resource = delete_match.group(1).strip() if delete_match else ""
        if params.get("resource_id") and not resource:
            resource = params["resource_id"].rstrip("/").split("/")[-1]
        api_match = re.search(r"\bapi_version\s+([A-Za-z0-9\-]+)", text, re.IGNORECASE)
        if api_match:
            params["api_version"] = api_match.group(1)
        risk = "High"
    elif "create resource group" in msg:
        action_type = "create_resource_group"
        create_rg_match = re.search(r"create\s+resource\s+group\s+([A-Za-z0-9_.()\-]+)", text, re.IGNORECASE)
        resource = create_rg_match.group(1) if create_rg_match else params.get("resource_group", "")
        params["resource_group"] = resource
        risk = "Low"
    elif "create storage account" in msg:
        action_type = "create_storage_account"
        storage_match = re.search(r"create\s+storage\s+account\s+([a-z0-9]{3,24})", text, re.IGNORECASE)
        sku_match = re.search(r"\bsku\s+([A-Za-z0-9_]+)", text, re.IGNORECASE)
        resource = storage_match.group(1).lower() if storage_match else ""
        if sku_match:
            params["sku"] = sku_match.group(1)
        risk = "Medium"

    if not action_type:
        return None
    if not resource:
        return _chat_error(
            "I understood the operation, but I need the resource name. Example: stop vm my-vm rg my-resource-group.",
            agent="remediation_agent",
        )

    try:
        approval = await create_approval_request(
            action_type=action_type,
            resource_id=resource,
            justification=justification,
            risk=risk,
            params=params,
        )
    except ValueError as exc:
        return _chat_error(
            f"Approval was not created because this operation is blocked by guardrail.\n{exc}\n"
            "If this resource must be changed, turn off protection from Guardrails using the Azure client ID and secret.",
            agent="guardrail_agent",
        )
    response = (
        f"I created approval {approval['id']} for exact action `{action_type}` on `{resource}`.\n"
        f"Risk: {risk}.\n"
        "Guardrails will still block execution if the resource becomes protected before approval.\n"
        "To execute it from chat, send: approve "
        f"{approval['id']}"
    )
    return {
        "response": response,
        "agent_used": "remediation_agent",
        "tool_results": [{"tool": "create_approval_request", "result": approval}],
        "actions_proposed": [approval],
        "error": None,
    }


def _chat_error(message: str, agent: str = "chatops_agent") -> dict:
    return {
        "response": message,
        "agent_used": agent,
        "tool_results": [],
        "actions_proposed": [],
        "error": None,
    }


@router.get("/agents")
async def list_agents():
    """List all available specialist agents and their capabilities."""
    return {
        "agents": [
            {
                "id": "finops_agent",
                "name": "FinOps Analyst",
                "description": "Azure cost analysis, budget tracking, spend optimisation",
                "tools": ["get_cost_summary", "get_cost_by_service", "get_budget_status", "propose_action"],
            },
            {
                "id": "cloudops_agent",
                "name": "CloudOps Engineer",
                "description": "Resource health, infrastructure inventory, Advisor recommendations",
                "tools": ["list_resources", "get_advisor_recommendations", "get_resource_health", "propose_action"],
            },
            {
                "id": "anomaly_agent",
                "name": "Anomaly Detector",
                "description": "Cost anomaly detection, unusual spend pattern analysis",
                "tools": ["get_anomalies", "get_cost_summary", "get_cost_by_service"],
            },
            {
                "id": "forecast_agent",
                "name": "Cost Forecaster",
                "description": "ML-based cost forecasting and budget projection",
                "tools": ["get_cost_forecast", "get_cost_summary"],
            },
            {
                "id": "approval_agent",
                "name": "Approval Manager",
                "description": "Pending approvals, proposed actions, remediation queue",
                "tools": ["list_pending_approvals"],
            },
            {
                "id": "security_agent",
                "name": "Security Analyst",
                "description": "Defender for Cloud findings, policy compliance, and secure operations",
                "tools": ["get_security_posture", "get_policy_compliance"],
            },
        ]
    }


@router.get("/tools")
async def list_tools():
    """List all MCP tools registered in the system."""
    from mcp_layer.tools import all_tools_schema
    return {"tools": all_tools_schema()}
