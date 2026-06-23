from __future__ import annotations

import logging
from typing import Any, Dict

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


ACTION_REGISTRY: Dict[str, str] = {
    "stop_vm": "Deallocate an Azure VM to eliminate compute charges",
    "start_vm": "Start an Azure VM",
    "restart_vm": "Restart an Azure VM",
    "resize_vm": "Resize a VM to a different SKU",
    "restart_app_service": "Restart an Azure App Service",
    "stop_app_service": "Stop an Azure App Service",
    "start_app_service": "Start an Azure App Service",
    "restore_blob": "Restore a blob from a backup container",
    "scale_container_app": "Scale Azure Container App replica counts",
    "delete_resource": "Delete a selected Azure resource by ARM resource ID",
    "create_resource_group": "Create an Azure resource group",
    "create_storage_account": "Create a StorageV2 Azure Storage account",
    "vm_downsize": "Resize VM to a smaller SKU during off-peak hours",
    "vm_shutdown": "Shut down an idle VM and deallocate resources",
    "enable_autoscale": "Attach an autoscale profile to an App Service or VMSS",
    "delete_storage": "Permanently delete a blob container or storage account",
    "reserve_instances": "Purchase reserved VM instances via Azure Reservations API",
    "restart_service": "Restart a failing App Service",
    "terraform_apply": "Apply a pre-validated Terraform change plan",
}

ACTION_ALIASES: Dict[str, str] = {
    "delete_unused": "delete_resource",
    "remove_resource": "delete_resource",
    "destroy_resource": "delete_resource",
    "restart_service": "restart_app_service",
    "stop_service": "stop_app_service",
    "start_service": "start_app_service",
    "vm_shutdown": "stop_vm",
    "scale_down": "scale_container_app",
}


class RemediationAgent(BaseAgent):
    name = "Remediation Agent"
    description = "Approval-gated fix execution for FinOps and CloudOps actions"

    system_prompt = """
You are FinOps.AI's Remediation Agent. You propose and, after approval, execute
infrastructure changes to optimise cost and fix cloud health issues.

Strict rules:
- Never execute any action without explicit approval recorded in the system.
- Always include rollback guidance for proposed actions.
- For destructive actions, mark risk as Medium or High.
- Log every action with timestamp, user, and outcome for audit.
"""

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = payload.get("message", "")
        history = payload.get("history", [])
        response_text = await self.chat(
            user_message=message,
            conversation_history=history,
            context=self._get_action_registry_context(),
        )
        return {
            "response": response_text,
            "actions": [],
            "sources": ["MCP Execution tools", "Approval Queue", "Azure SDK"],
        }

    async def execute_approved_action(
        self,
        approval_id: str,
        action_type: str,
        resource: str,
        params: Dict[str, Any],
        approved_by: str,
    ) -> Dict[str, Any]:
        logger.info(
            "[Remediation] Executing approved action: %s on %s by %s (%s)",
            action_type,
            resource,
            approved_by,
            approval_id,
        )

        action_type, resource, params = self._normalise_action(action_type, resource, params or {})
        from services import guardrail_service

        guard = guardrail_service.evaluate_execution(action_type, resource, params)
        if not guard.get("allowed", True):
            return {
                "status": "blocked_by_guardrail",
                "success": False,
                "action": action_type,
                "resource": resource,
                "error": guard.get("reason", "Blocked by guardrail."),
                "guardrail": guard,
            }

        if action_type not in ACTION_REGISTRY:
            raise ValueError(f"Unknown action type: {action_type}")

        handlers = {
            "stop_vm": self._exec_stop_vm,
            "vm_shutdown": self._exec_stop_vm,
            "start_vm": self._exec_start_vm,
            "restart_vm": self._exec_restart_vm,
            "resize_vm": self._exec_resize_vm,
            "vm_downsize": self._exec_resize_vm,
            "restart_app_service": self._exec_restart_app_service,
            "stop_app_service": self._exec_stop_app_service,
            "start_app_service": self._exec_start_app_service,
            "restart_service": self._exec_restart_app_service,
            "restore_blob": self._exec_restore_blob,
            "scale_container_app": self._exec_scale_container_app,
            "delete_resource": self._exec_delete_resource,
            "create_resource_group": self._exec_create_resource_group,
            "create_storage_account": self._exec_create_storage_account,
            "enable_autoscale": self._unsupported,
            "delete_storage": self._unsupported,
            "reserve_instances": self._unsupported,
            "terraform_apply": self._unsupported,
        }
        return await handlers[action_type](resource, params or {})

    async def _exec_stop_vm(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("stop_vm", resource, params)

    async def _exec_start_vm(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("start_vm", resource, params)

    async def _exec_restart_vm(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("restart_vm", resource, params)

    async def _exec_resize_vm(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("resize_vm", resource, params)

    async def _exec_restart_app_service(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("restart_app_service", resource, params)

    async def _exec_stop_app_service(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("stop_app_service", resource, params)

    async def _exec_start_app_service(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("start_app_service", resource, params)

    async def _exec_restore_blob(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("restore_blob", resource, params)

    async def _exec_scale_container_app(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("scale_container_app", resource, params)

    async def _exec_delete_resource(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("delete_resource", resource, params)

    async def _exec_create_resource_group(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("create_resource_group", resource, params)

    async def _exec_create_storage_account(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self._execute_mcp_tool("create_storage_account", resource, params)

    async def _unsupported(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "unsupported",
            "success": False,
            "resource": resource,
            "params": params,
            "message": "This execution action is not configured yet.",
        }

    def _normalise_action(
        self,
        action_type: str,
        resource: str,
        params: Dict[str, Any],
    ) -> tuple[str, str, Dict[str, Any]]:
        action_type = str(action_type or "").strip()
        resource = str(resource or "").strip()
        params = dict(params or {})
        canonical = ACTION_ALIASES.get(action_type, action_type)

        if canonical == "delete_resource":
            resource_id = params.get("resource_id") or (resource if self._looks_like_arm_id(resource) else "")
            if not resource_id:
                raise ValueError(
                    "Delete requires one exact ARM resource_id. Broad delete requests such as "
                    "'delete_unused' are not executable until the user selects a specific resource."
                )
            params["resource_id"] = resource_id
            resource = resource_id

        return canonical, resource, params

    async def _execute_mcp_tool(self, tool_name: str, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from mcp_layer.tool_registry import tool_registry

        tool = tool_registry.get_tool(tool_name)
        if not tool:
            return {"status": "failed", "success": False, "action": tool_name, "error": "MCP execution tool is not registered."}

        arguments = dict(params or {})
        arguments.setdefault("resource_name", resource)
        if self._looks_like_arm_id(resource):
            arguments.setdefault("resource_id", resource)
        self._hydrate_from_arm_id(arguments)
        await self._hydrate_resource_arguments(arguments, tool_name)
        result = await tool.fn(**arguments)
        if isinstance(result, dict):
            result.setdefault("status", "success" if result.get("success") else "failed")
            return result
        return {"status": "success", "success": True, "action": tool_name, "result": result}

    async def _hydrate_resource_arguments(self, arguments: Dict[str, Any], tool_name: str) -> None:
        self._hydrate_from_arm_id(arguments)
        if arguments.get("resource_group") or not arguments.get("resource_name"):
            return

        type_hints = {
            "stop_vm": "microsoft.compute/virtualmachines",
            "start_vm": "microsoft.compute/virtualmachines",
            "restart_vm": "microsoft.compute/virtualmachines",
            "resize_vm": "microsoft.compute/virtualmachines",
            "restart_app_service": "microsoft.web/sites",
            "stop_app_service": "microsoft.web/sites",
            "start_app_service": "microsoft.web/sites",
            "scale_container_app": "microsoft.app/containerapps",
        }
        expected_type = type_hints.get(tool_name, "")
        if not expected_type:
            return

        try:
            from services.azure_resource_service import get_all_resources

            inventory = await get_all_resources()
            target = str(arguments.get("resource_name", "")).lower()
            for item in inventory.get("resources", []):
                raw_type = str(item.get("raw_type") or item.get("type") or "").lower()
                if item.get("name", "").lower() == target and expected_type in raw_type:
                    arguments["resource_group"] = item.get("resource_group", "")
                    arguments.setdefault("resource_id", item.get("id", ""))
                    return
        except Exception as exc:
            logger.warning("Could not resolve resource group for %s/%s: %s", tool_name, arguments.get("resource_name"), exc)

    def _hydrate_from_arm_id(self, arguments: Dict[str, Any]) -> None:
        resource_id = str(arguments.get("resource_id") or arguments.get("resource_name") or "")
        parsed = self._parse_arm_id(resource_id)
        if not parsed:
            return
        arguments.setdefault("resource_id", parsed["id"])
        arguments["resource_name"] = parsed["resource_name"]
        arguments.setdefault("resource_group", parsed.get("resource_group", ""))
        arguments.setdefault("resource_type", parsed.get("resource_type", ""))

    @staticmethod
    def _looks_like_arm_id(value: str) -> bool:
        return str(value or "").lower().startswith("/subscriptions/") and "/providers/" in str(value or "").lower()

    @classmethod
    def _parse_arm_id(cls, value: str) -> Dict[str, str] | None:
        if not cls._looks_like_arm_id(value):
            return None
        parts = [part for part in str(value).strip("/").split("/") if part]
        lowered = [part.lower() for part in parts]
        try:
            rg = parts[lowered.index("resourcegroups") + 1] if "resourcegroups" in lowered else ""
            provider_index = lowered.index("providers")
            provider = parts[provider_index + 1]
            tail = parts[provider_index + 2:]
            resource_type = f"{provider}/{tail[-2]}" if len(tail) >= 2 else provider
            resource_name = tail[-1] if tail else parts[-1]
            return {
                "id": value,
                "resource_group": rg,
                "resource_type": resource_type,
                "resource_name": resource_name,
            }
        except Exception:
            return None

    def _get_action_registry_context(self) -> str:
        return "Available remediation action types:\n" + "\n".join(
            f"- {key}: {value}" for key, value in ACTION_REGISTRY.items()
        )
