"""
routers/mcp_tools.py — MCP Tool Server API endpoints

Exposes the MCP tool layer via REST so:
  • Frontend can list/call tools from the Settings page
  • Swagger docs show all registered tools
  • Agents can call tools via HTTP in Phase 4 (LangGraph)

Endpoints:
  GET  /api/v1/mcp/tools                    → list all tools
  GET  /api/v1/mcp/tools/{server}           → list tools for one server
  POST /api/v1/mcp/execute/{tool_name}      → execute a tool
  GET  /api/v1/mcp/audit                    → recent tool call audit log
  GET  /api/v1/mcp/servers                  → server summary stats
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

import mcp_layer  # triggers registration of all tools
from mcp_layer.tool_registry import tool_registry

router = APIRouter()


class ToolExecuteRequest(BaseModel):
    args: Dict[str, Any] = {}


@router.get("/tools")
async def list_all_tools():
    """List every registered MCP tool across all 5 servers."""
    tools    = tool_registry.list_tools()
    summary  = tool_registry.server_summary()
    return {
        "total_tools": len(tools),
        "servers":     summary,
        "tools":       tools,
    }


@router.get("/tools/{server}")
async def list_server_tools(server: str):
    """List tools for a specific MCP server (finops, cloudops, execution, notification, knowledge)."""
    tools = tool_registry.list_tools(server=server)
    if not tools:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{server}' not found. Available: finops, cloudops, execution, notification, knowledge"
        )
    return {"server": server, "total": len(tools), "tools": tools}


@router.post("/execute/{tool_name}")
async def execute_tool(tool_name: str, body: ToolExecuteRequest):
    """
    Execute a registered MCP tool by name.

    Example:
      POST /api/v1/mcp/execute/get_cost_summary
      POST /api/v1/mcp/execute/get_resource_inventory
      POST /api/v1/mcp/execute/send_teams_alert
        { "args": { "title": "Test", "severity": "info" } }
    """
    result = await tool_registry.execute(tool_name, **body.args)
    if not result["success"] and result.get("requires_approval"):
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{tool_name}' requires human approval via the Approval Queue."
        )
    return result


@router.get("/audit")
async def get_audit_log(limit: int = 50):
    """Recent MCP tool call audit log (newest first)."""
    return {
        "log":   tool_registry.get_audit_log(limit=limit),
        "total": limit,
    }


@router.get("/servers")
async def get_server_summary():
    """Stats per MCP server: tool count, total calls, errors."""
    return tool_registry.server_summary()
