from __future__ import annotations

import logging
import re
from typing import Any

from agents.router import agent_router
from models.schemas import AgentName
from services.azure_account import configured_account, reset_current_account, set_current_account
from services import approval_service, audit_service

from app.integrations.teams.adapter import send_activity
from app.integrations.teams.cards import approval_attachment, text_attachment
from app.integrations.teams.notifications import save_conversation_reference
from app.integrations.teams.schemas import TeamsActivity

logger = logging.getLogger("finops.teams.handlers")


async def handle_activity(activity: TeamsActivity) -> dict[str, Any]:
    logger.info(
        "Teams activity received: type=%s channel=%s conversation=%s from=%s",
        activity.type,
        activity.channel_id,
        activity.conversation.id,
        activity.from_property.id,
    )
    save_conversation_reference(activity)

    if activity.type in {"conversationUpdate", "installationUpdate"}:
        await send_activity(activity, "FinOps.AI is connected. Ask about Azure cost, resources, security, forecasts, or approvals.")
        return {"handled": True, "activity_type": activity.type}

    if activity.type != "message":
        return {"handled": True, "activity_type": activity.type, "ignored": True}

    if activity.value and activity.value.get("finops_action") == "approval_decision":
        return await _handle_approval_card(activity)

    text = _clean_teams_text(activity.text)
    if not text:
        await send_activity(activity, "Send a FinOps or CloudOps question, for example: show my Azure cost.")
        return {"handled": True, "empty": True}

    return await _handle_message(activity, text)


async def _handle_message(activity: TeamsActivity, text: str) -> dict[str, Any]:
    token = set_current_account(configured_account())
    try:
        try:
            from agents.langgraph_orchestrator import run_agent

            result = await run_agent(message=text, history=[])
            if result.get("error"):
                logger.warning("Teams LangGraph result returned error: %s", result.get("error"))
                result = await _direct_chatops_fallback(text)
        except Exception as exc:
            logger.exception("Teams LangGraph execution failed")
            result = await _direct_chatops_fallback(text, error=str(exc))
    finally:
        reset_current_account(token)

    attachments = []
    for approval in _extract_approvals(result):
        attachments.append(approval_attachment(approval))

    response = result.get("response") or "I processed the request but did not receive a text response."
    if attachments:
        response += "\n\nI also created approval card(s) for the proposed action."
    await send_activity(activity, response, attachments=attachments)
    logger.info("Teams response sent via agent=%s approvals=%s", result.get("agent_used"), len(attachments))
    return {"handled": True, "agent_used": result.get("agent_used"), "approvals": len(attachments)}


async def _handle_approval_card(activity: TeamsActivity) -> dict[str, Any]:
    value = activity.value or {}
    approval_id = str(value.get("approval_id") or "")
    decision = str(value.get("decision") or "").lower()
    actor = activity.from_property.name or activity.from_property.id or "teams-user"
    if decision not in {"approved", "rejected"} or not approval_id:
        await send_activity(activity, "I could not read the approval decision from this card.")
        return {"handled": True, "error": "invalid_approval_card"}

    try:
        from services.approval_execution_service import decide_and_maybe_execute

        result = await decide_and_maybe_execute(
            approval_id=approval_id,
            decision=decision,
            decided_by=actor,
            notes="Decided from Microsoft Teams",
            account=configured_account(),
        )
    except ValueError as exc:
        await send_activity(activity, str(exc))
        return {"handled": True, "error": str(exc)}

    execution_result = result.get("execution_result")
    outcome = "success" if result.get("execution_succeeded") is not False else "failed"
    message = f"{approval_id} was {decision} by {actor}."
    if decision == "approved" and result.get("execution_succeeded") is False:
        message = f"{approval_id} could not execute yet, so it is still pending."
    if execution_result:
        message += f"\nExecution status: {execution_result.get('status') or ('success' if execution_result.get('success') else 'failed')}."
        if execution_result.get("error"):
            message += f"\nError: {execution_result['error']}"
    await send_activity(activity, message)
    logger.info("Teams approval decision processed: %s %s outcome=%s", approval_id, decision, outcome)
    return {"handled": True, "approval_id": approval_id, "decision": decision, "execution_result": execution_result}


async def _direct_chatops_fallback(text: str, error: str = "") -> dict[str, Any]:
    from routers.chat import _chatops_without_llm

    result = await _chatops_without_llm(text, configured_account())
    if error:
        result["error"] = error
        result["response"] = f"LangGraph failed, so I used direct ChatOps tools.\n\n{result['response']}"
    return result


def _extract_approvals(result: dict[str, Any]) -> list[dict[str, Any]]:
    approvals: list[dict[str, Any]] = []
    for item in result.get("actions_proposed") or []:
        if isinstance(item, dict) and item.get("id"):
            approvals.append(item)
    for tool_result in result.get("tool_results") or []:
        payload = tool_result.get("result") if isinstance(tool_result, dict) else None
        if isinstance(payload, dict) and payload.get("id") and payload.get("status") == "pending":
            approvals.append(payload)
    seen = set()
    unique = []
    for approval in approvals:
        approval_id = approval.get("id")
        if approval_id not in seen:
            unique.append(approval)
            seen.add(approval_id)
    return unique


def _execution_outcome(decision: str, execution_result: dict[str, Any] | None) -> str:
    if decision == "rejected":
        return "success"
    if not execution_result:
        return "failed"
    return "success" if execution_result.get("status") != "failed" and execution_result.get("success") is not False else "failed"


def _clean_teams_text(text: str) -> str:
    text = re.sub(r"<at>.*?</at>", "", text or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
