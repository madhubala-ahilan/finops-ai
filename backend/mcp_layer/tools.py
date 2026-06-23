"""
mcp_layer/tools.py — Model Context Protocol-style Tool Registry

Each tool is a typed, async function that agents can call by name.
The registry maps tool names → callables, with schemas for GPT function calling.

Tools exposed:
  COST:      get_cost_summary, get_cost_by_service, get_budget_status
  CLOUDOPS:  list_resources, get_advisor_recs, get_resource_health
  ANOMALY:   get_anomalies, run_anomaly_scan
  FORECAST:  get_cost_forecast
  APPROVAL:  list_pending_approvals, approve_action, reject_action
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger("finops.mcp")


# ─── Tool decorator + registry ────────────────────────────────────────────────

_REGISTRY: dict[str, dict] = {}


def tool(name: str, description: str, parameters: dict):
    """Decorator that registers a function as an MCP tool."""
    def decorator(fn: Callable):
        _REGISTRY[name] = {
            "fn": fn,
            "description": description,
            "parameters": parameters,
        }
        return fn
    return decorator


def get_tool(name: str) -> Callable | None:
    entry = _REGISTRY.get(name)
    return entry["fn"] if entry else None


def all_tools_schema() -> list[dict]:
    """Returns OpenAI function-calling schema for all registered tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": entry["description"],
                "parameters": entry["parameters"],
            },
        }
        for name, entry in _REGISTRY.items()
    ]


def agent_tools_schema(tool_names: list[str]) -> list[dict]:
    """Returns schema for a specific subset of tools."""
    return [t for t in all_tools_schema() if t["function"]["name"] in tool_names]


# ─── Cost Tools ───────────────────────────────────────────────────────────────

@tool(
    name="get_cost_summary",
    description=(
        "Get the Azure subscription cost summary: month-to-date spend, "
        "last month spend, budget utilisation, and daily trend."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_cost_summary() -> dict:
    from services.azure_cost_service import get_mtd_summary
    return await get_mtd_summary()


@tool(
    name="get_cost_by_service",
    description="Get Azure cost breakdown by service for the past N days.",
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 30)",
            }
        },
        "required": [],
    },
)
async def get_cost_by_service_tool(days: int = 30) -> dict:
    from services.azure_cost_service import get_cost_by_service
    return await get_cost_by_service(days=days)


@tool(
    name="get_budget_status",
    description="Check current budget utilisation percentage and remaining budget.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_budget_status() -> dict:
    from services.azure_cost_service import get_mtd_summary
    summary = await get_mtd_summary()
    budget   = summary.get("budget_monthly", 0)
    spent    = summary.get("mtd_spend", 0)
    remaining = max(0.0, budget - spent)
    return {
        "budget_monthly": budget,
        "spent_mtd": spent,
        "remaining": round(remaining, 2),
        "currency": summary.get("currency", "USD"),
        "utilisation_pct": summary.get("budget_utilisation_pct", 0),
        "status": (
            "critical" if summary.get("budget_utilisation_pct", 0) > 90
            else "warning" if summary.get("budget_utilisation_pct", 0) > 75
            else "healthy"
        ),
    }


# ─── CloudOps Tools ───────────────────────────────────────────────────────────

@tool(
    name="list_resources",
    description=(
        "List all Azure resources in the subscription. "
        "Returns name, type, region, resource group, and health status."
    ),
    parameters={
        "type": "object",
        "properties": {
            "resource_type": {
                "type": "string",
                "description": "Optional filter by resource type (e.g. 'Virtual Machine')",
            }
        },
        "required": [],
    },
)
async def list_resources_tool(resource_type: str | None = None) -> dict:
    from services.azure_resource_service import get_all_resources
    result = await get_all_resources()
    if resource_type:
        result["resources"] = [
            r for r in result.get("resources", [])
            if resource_type.lower() in r.get("type", "").lower()
        ]
    return result


@tool(
    name="get_advisor_recommendations",
    description=(
        "Fetch Azure Advisor recommendations for cost optimisation, "
        "security, reliability, and performance."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["Cost", "Security", "HighAvailability", "Performance", "OperationalExcellence"],
                "description": "Optional filter by recommendation category",
            }
        },
        "required": [],
    },
)
async def get_advisor_recommendations_tool(category: str | None = None) -> dict:
    from services.azure_resource_service import get_advisor_recommendations
    recs = await get_advisor_recommendations()
    if category:
        recs = [r for r in recs if r.get("category", "").lower() == category.lower()]
    return {"total": len(recs), "recommendations": recs}


@tool(
    name="get_resource_health",
    description="Get Azure Resource Health availability summary across the subscription.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_resource_health_tool() -> dict:
    from services.azure_resource_service import get_resource_health_summary
    return await get_resource_health_summary()


@tool(
    name="get_security_posture",
    description="Get live Azure security posture from Resource Graph securityresources.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_security_posture_tool() -> dict:
    from agents.security_agent import get_security_posture
    return await get_security_posture()


@tool(
    name="get_policy_compliance",
    description="Get live Azure Policy non-compliance summary from Policy Insights.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_policy_compliance_tool() -> dict:
    from services.azure_policy_service import get_policy_compliance_summary
    return await get_policy_compliance_summary()


# ─── Anomaly Tools ────────────────────────────────────────────────────────────

@tool(
    name="get_anomalies",
    description="Get detected cost and performance anomalies from the anomaly detection engine.",
    parameters={
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["critical", "warning", "info"],
                "description": "Optional filter by severity",
            }
        },
        "required": [],
    },
)
async def get_anomalies_tool(severity: str | None = None) -> dict:
    """Returns current anomaly detections (from in-memory store or ML engine)."""
    try:
        from services.anomaly_service import get_current_anomalies
        return await get_current_anomalies(severity=severity)
    except ImportError:
        # Fallback: return empty
        return {"anomalies": [], "total": 0, "note": "Anomaly service not initialised."}


@tool(
    name="get_cost_forecast",
    description="Get ML-based cost forecast for the next 30 days based on historical spend.",
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of days to forecast (default 30, max 90)",
            }
        },
        "required": [],
    },
)
async def get_cost_forecast_tool(days: int = 30) -> dict:
    try:
        from services.azure_cost_service import get_mtd_summary
        from ml.xgboost_forecast import forecast_spend

        data = await get_mtd_summary()
        trend = data.get("trend", [])
        if len(trend) < 5:
            return {
                "forecast": [],
                "confidence": "low",
                "data_source": "empty",
                "note": f"Need at least 5 live daily cost points; Azure returned {len(trend)}.",
            }
        result = forecast_spend(
            [point["amount"] for point in trend],
            horizon=min(days, 90),
            trend_objects=trend,
        )
        result["data_source"] = data.get("data_source", "live")
        return result
    except Exception as exc:
        return {
            "forecast": [],
            "confidence": "low",
            "data_source": "error",
            "note": f"Forecast engine failed: {exc}",
        }


# ─── Approval Tools ───────────────────────────────────────────────────────────

@tool(
    name="list_pending_approvals",
    description="List all pending approval requests for AI-proposed remediation actions.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def list_pending_approvals_tool() -> dict:
    try:
        from services.approval_service import get_pending_approvals
        approvals = await get_pending_approvals()
        return {"pending": approvals, "total": len(approvals)}
    except ImportError:
        return {"pending": [], "total": 0}


@tool(
    name="propose_action",
    description=(
        "Propose a remediation or optimisation action that requires human approval "
        "before execution. Use for resource resizing, cost optimisations, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "description": "Type of action (e.g. 'resize_vm', 'delete_unused', 'scale_down')",
            },
            "resource_id": {
                "type": "string",
                "description": "Azure resource ID or name to act on",
            },
            "justification": {
                "type": "string",
                "description": "Why this action is recommended",
            },
            "estimated_savings": {
                "type": "number",
                "description": "Estimated monthly savings in USD (if applicable)",
            },
        },
        "required": ["action_type", "resource_id", "justification"],
    },
)
async def propose_action_tool(
    action_type: str,
    resource_id: str,
    justification: str,
    estimated_savings: float = 0.0,
) -> dict:
    try:
        from services.approval_service import create_approval_request
        result = await create_approval_request(
            action_type=action_type,
            resource_id=resource_id,
            justification=justification,
            estimated_savings=estimated_savings,
        )
        return result
    except ImportError:
        return {
            "id": f"pending_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "status": "pending_approval",
            "action_type": action_type,
            "resource_id": resource_id,
            "justification": justification,
            "estimated_savings": estimated_savings,
            "created_at": datetime.utcnow().isoformat(),
        }


# ─── Tool executor ────────────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict | str) -> Any:
    """
    Execute a registered tool by name with the given arguments.
    arguments can be a dict or a JSON string (from GPT function call).
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    entry = _REGISTRY.get(name)
    if not entry:
        return {"error": f"Unknown tool: {name}"}

    try:
        fn = entry["fn"]
        result = fn(**arguments)
        # Support both sync and async tools
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc)
        return {"error": f"Tool execution failed: {exc}"}
