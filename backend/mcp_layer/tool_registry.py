"""
mcp/tool_registry.py — Central MCP-Inspired Tool Registry

Architecture:
  Agents NEVER call Azure SDK directly.
  They call: await tool_registry.execute("tool_name", **args)

  This is Option B: MCP-inspired internal tool abstraction.
  Same pattern as real MCP, implemented in Python for deadline speed.
  Designed to migrate to full MCP protocol easily.

  In presentation say:
  "MCP-inspired modular tool server architecture, designed for
   migration to full MCP protocol."

Tool servers registered:
  finops       → cost, budget, advisor, forecast, anomaly
  cloudops     → resources, health, metrics, blob
  execution    → stop_vm, restart, restore, scale  (approval-gated)
  notification → teams, email, voice
  knowledge    → search, playbooks, pricing docs

Usage:
  from mcp_layer.tool_registry import tool_registry

  result = await tool_registry.execute("get_cost_summary")
  result = await tool_registry.execute("send_teams_alert",
                                       title="Budget breach!",
                                       severity="critical")
"""

from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("finops.mcp.registry")


class MCPTool:
    """Metadata + callable for one registered tool."""

    def __init__(
        self,
        name: str,
        fn: Callable,
        server: str,
        description: str,
        requires_approval: bool = False,
        tags: Optional[List[str]] = None,
    ):
        self.name              = name
        self.fn                = fn
        self.server            = server
        self.description       = description
        self.requires_approval = requires_approval
        self.tags              = tags or []
        self.call_count        = 0
        self.error_count       = 0
        self.last_called_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "name":               self.name,
            "server":             self.server,
            "description":        self.description,
            "requires_approval":  self.requires_approval,
            "tags":               self.tags,
            "call_count":         self.call_count,
            "error_count":        self.error_count,
            "last_called_at":     self.last_called_at,
        }


class ToolRegistry:
    """
    Central MCP-inspired tool registry.

    Agents call tools through here — they never import Azure SDK clients
    directly. This gives us:
      • Clean agent code (no SDK coupling)
      • Centralised audit logging of every tool call
      • Governance hook before execution tools fire
      • One place to add auth, rate-limiting, retries
    """

    def __init__(self):
        self._tools:     Dict[str, MCPTool] = {}
        self._audit_log: List[Dict]         = []

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        server: str,
        description: str = "",
        requires_approval: bool = False,
        tags: Optional[List[str]] = None,
    ) -> Callable:
        """
        Decorator: registers an async function as an MCP tool.

        @tool_registry.register(
            name="get_cost_summary",
            server="finops",
            description="Month-to-date Azure spend summary",
        )
        async def get_cost_summary(**kwargs) -> dict:
            ...
        """
        def decorator(fn: Callable) -> Callable:
            self._tools[name] = MCPTool(
                name=name,
                fn=fn,
                server=server,
                description=description,
                requires_approval=requires_approval,
                tags=tags or [],
            )
            logger.debug(f"MCP tool registered: [{server}] {name}")
            return fn
        return decorator

    # ── Execution ─────────────────────────────────────────────────────────────

    async def execute(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a registered MCP tool by name.

        Returns a standardised response envelope:
          {
            "tool":    "tool_name",
            "server":  "finops",
            "success": True,
            "data":    { ... },   # tool's return value
            "error":   None,
            "latency_ms": 42,
          }
        """
        tool = self._tools.get(tool_name)
        if not tool:
            available = list(self._tools.keys())
            logger.error(f"Tool '{tool_name}' not found. Available: {available}")
            return self._error_response(
                tool_name, f"Tool '{tool_name}' not registered. Available: {available}"
            )

        # ── Governance gate for execution tools ───────────────────────────────
        if tool.requires_approval:
            approval_check = await self._governance_gate(tool_name, kwargs)
            if not approval_check["approved"]:
                return self._error_response(
                    tool_name,
                    f"Blocked by governance: {approval_check['reason']}",
                    requires_approval=True,
                )

        # ── Execute ───────────────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            result = await tool.fn(**kwargs)
            latency = round((time.monotonic() - t0) * 1000, 1)

            tool.call_count     += 1
            tool.last_called_at  = datetime.now(timezone.utc).isoformat()

            self._audit(tool_name, tool.server, kwargs, success=True,
                        latency_ms=latency)
            logger.info(f"[MCP] {tool.server}/{tool_name} → OK ({latency}ms)")

            return {
                "tool":       tool_name,
                "server":     tool.server,
                "success":    True,
                "data":       result,
                "error":      None,
                "latency_ms": latency,
                "called_at":  tool.last_called_at,
            }

        except Exception as exc:
            latency = round((time.monotonic() - t0) * 1000, 1)
            tool.error_count += 1
            self._audit(tool_name, tool.server, kwargs, success=False,
                        latency_ms=latency, error=str(exc))
            logger.error(
                f"[MCP] {tool.server}/{tool_name} → ERROR "
                f"({latency}ms): {type(exc).__name__}: {exc}"
            )
            return self._error_response(tool_name, f"{type(exc).__name__}: {exc}")

    # ── Query / introspection ─────────────────────────────────────────────────

    def list_tools(self, server: Optional[str] = None) -> List[Dict]:
        """List all registered tools, optionally filtered by server."""
        tools = self._tools.values()
        if server:
            tools = [t for t in tools if t.server == server]
        return [t.to_dict() for t in tools]

    def get_tool(self, name: str) -> Optional[MCPTool]:
        return self._tools.get(name)

    def server_summary(self) -> Dict[str, Dict]:
        """Summary stats per MCP server."""
        summary: Dict[str, Dict] = {}
        for tool in self._tools.values():
            s = summary.setdefault(tool.server, {
                "tools": 0, "calls": 0, "errors": 0
            })
            s["tools"]  += 1
            s["calls"]  += tool.call_count
            s["errors"] += tool.error_count
        return summary

    def get_audit_log(self, limit: int = 50) -> List[Dict]:
        return list(reversed(self._audit_log[-limit:]))

    # ── Governance gate ───────────────────────────────────────────────────────

    async def _governance_gate(
        self, tool_name: str, kwargs: Dict
    ) -> Dict:
        """
        Pre-execution governance check for approval-gated tools.
        Connects to GovernanceAgent in Phase 4.
        Currently: all execution tools require manual approval via Approval Queue.
        """
        try:
            from agents.governance_agent import get_governance_agent
            agent = get_governance_agent()
            result = await agent.validate_action({
                "action_type": tool_name,
                "resource":    kwargs.get("resource_name", kwargs.get("resource", "")),
                "risk":        kwargs.get("risk", "Medium"),
                "proposed_by": "MCPToolRegistry",
            })
            approved = result.get("decision") == "AUTO_APPROVED"
            return {
                "approved": approved,
                "reason":   result.get("reason", ""),
                "decision": result.get("decision"),
            }
        except Exception as exc:
            logger.warning(f"Governance gate error: {exc} — defaulting to BLOCKED for safety")
            return {
                "approved": False,
                "reason":   "Governance service unavailable — blocked for safety",
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _audit(
        self, tool_name: str, server: str, args: Dict,
        success: bool, latency_ms: float, error: str = ""
    ):
        self._audit_log.append({
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "tool":       tool_name,
            "server":     server,
            "args_keys":  list(args.keys()),
            "success":    success,
            "latency_ms": latency_ms,
            "error":      error,
        })
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-1000:]

    @staticmethod
    def _error_response(
        tool_name: str, error: str, requires_approval: bool = False
    ) -> Dict:
        return {
            "tool":               tool_name,
            "server":             "unknown",
            "success":            False,
            "data":               None,
            "error":              error,
            "latency_ms":         0,
            "requires_approval":  requires_approval,
        }


# ── Global singleton ──────────────────────────────────────────────────────────
# Import this everywhere:  from mcp_layer.tool_registry import tool_registry

tool_registry = ToolRegistry()
