from __future__ import annotations

from typing import Any


def text_attachment(title: str, text: str, severity: str = "info") -> dict[str, Any]:
    color = {
        "critical": "Attention",
        "warning": "Warning",
        "success": "Good",
        "resolved": "Good",
        "info": "Accent",
    }.get(severity.lower(), "Default")
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "color": color},
                {"type": "TextBlock", "text": text, "wrap": True},
            ],
        },
    }


def approval_attachment(approval: dict[str, Any]) -> dict[str, Any]:
    approval_id = approval.get("id", "")
    resource = approval.get("resource") or approval.get("resource_id") or "resource"
    action = approval.get("action") or approval.get("action_type") or "Action"
    risk = approval.get("risk", "Medium")
    detail = approval.get("detail") or approval.get("justification") or "Approval requested from FinOps.AI."
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "text": "Approval Required", "weight": "Bolder", "size": "Medium", "color": "Warning"},
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "Approval", "value": approval_id},
                        {"title": "Action", "value": str(action)},
                        {"title": "Resource", "value": str(resource)},
                        {"title": "Risk", "value": str(risk)},
                    ],
                },
                {"type": "TextBlock", "text": str(detail), "wrap": True},
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Approve",
                    "style": "positive",
                    "data": {"finops_action": "approval_decision", "approval_id": approval_id, "decision": "approved"},
                },
                {
                    "type": "Action.Submit",
                    "title": "Reject",
                    "style": "destructive",
                    "data": {"finops_action": "approval_decision", "approval_id": approval_id, "decision": "rejected"},
                },
            ],
        },
    }
