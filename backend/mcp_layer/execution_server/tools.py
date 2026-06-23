"""
mcp/execution_server/tools.py — Execution MCP Server

⚠️  ALL tools in this server require_approval=True
    They go through GovernanceAgent before executing.
    The Approval Queue in the UI shows them for human sign-off.

Tools:
  stop_vm()              → Deallocate an Azure VM
  restart_app_service()  → Restart an App Service
  restore_blob()         → Restore a blob from backup
  scale_container_app()  → Scale a Container App instance count
  resize_vm()            → Resize VM to a different SKU

Used by:
  GovernanceAgent + RemedationAgent (after human approval)
"""

from mcp_layer.tool_registry import tool_registry


@tool_registry.register(
    name="stop_vm",
    server="execution",
    description="Deallocate (stop + deallocate) an Azure VM to eliminate compute charges",
    requires_approval=True,
    tags=["vm", "cost-saving", "compute"],
)
async def stop_vm(resource_name: str = "", resource_group: str = "", **kwargs) -> dict:
    """
    Stops and deallocates a VM — eliminates compute charges.
    Requires human approval via Approval Queue.

    Phase 4: Wire to azure.mgmt.compute ComputeManagementClient.
    """
    if not resource_name:
        return {"success": False, "error": "resource_name is required"}

    try:
        from azure.mgmt.compute import ComputeManagementClient
        from services.azure_account import current_account

        account = current_account()
        client = ComputeManagementClient(account.credential(), account.subscription_id)
        rg = resource_group
        if not rg:
            return {"success": False, "error": "resource_group is required"}

        # Begin async operation (long-running)
        poller = client.virtual_machines.begin_deallocate(rg, resource_name)
        result = poller.result(timeout=300)

        return {
            "success":         True,
            "action":          "deallocate",
            "vm_name":         resource_name,
            "resource_group":  rg,
            "status":          "Deallocated",
            "data_source":     "live",
        }

    except Exception as exc:
        return {
            "success":     False,
            "action":      "deallocate",
            "vm_name":     resource_name,
            "error":       str(exc),
            "data_source": "error",
            "note":        "Ensure SP has 'Virtual Machine Contributor' role",
        }


@tool_registry.register(
    name="start_vm",
    server="execution",
    description="Start an Azure VM",
    requires_approval=True,
    tags=["vm", "start", "compute"],
)
async def start_vm(resource_name: str = "", resource_group: str = "", **kwargs) -> dict:
    if not all([resource_name, resource_group]):
        return {"success": False, "error": "resource_name and resource_group are required"}
    try:
        from azure.mgmt.compute import ComputeManagementClient
        from services.azure_account import current_account

        account = current_account()
        client = ComputeManagementClient(account.credential(), account.subscription_id)
        poller = client.virtual_machines.begin_start(resource_group, resource_name)
        poller.result(timeout=300)
        return {
            "success": True,
            "action": "start",
            "vm_name": resource_name,
            "resource_group": resource_group,
            "status": "Started",
            "data_source": "live",
        }
    except Exception as exc:
        return {"success": False, "action": "start", "vm_name": resource_name, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="restart_vm",
    server="execution",
    description="Restart an Azure VM",
    requires_approval=True,
    tags=["vm", "restart", "compute", "incident"],
)
async def restart_vm(resource_name: str = "", resource_group: str = "", **kwargs) -> dict:
    if not all([resource_name, resource_group]):
        return {"success": False, "error": "resource_name and resource_group are required"}
    try:
        from azure.mgmt.compute import ComputeManagementClient
        from services.azure_account import current_account

        account = current_account()
        client = ComputeManagementClient(account.credential(), account.subscription_id)
        poller = client.virtual_machines.begin_restart(resource_group, resource_name)
        poller.result(timeout=300)
        return {
            "success": True,
            "action": "restart",
            "vm_name": resource_name,
            "resource_group": resource_group,
            "status": "Restarted",
            "data_source": "live",
        }
    except Exception as exc:
        return {"success": False, "action": "restart", "vm_name": resource_name, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="resize_vm",
    server="execution",
    description="Resize a VM to a different SKU (e.g. D4s_v3 → D2s_v3) for cost savings",
    requires_approval=True,
    tags=["vm", "resize", "cost-saving", "compute"],
)
async def resize_vm(
    resource_name: str = "",
    resource_group: str = "",
    target_sku: str = "",
    **kwargs,
) -> dict:
    if not all([resource_name, target_sku]):
        return {"success": False, "error": "resource_name and target_sku are required"}

    try:
        from azure.mgmt.compute import ComputeManagementClient
        from azure.mgmt.compute.models import HardwareProfile
        from services.azure_account import current_account

        account = current_account()
        client = ComputeManagementClient(account.credential(), account.subscription_id)
        rg = resource_group
        if not rg:
            return {"success": False, "error": "resource_group is required"}

        # Get current VM
        vm = client.virtual_machines.get(rg, resource_name)
        original_sku = vm.hardware_profile.vm_size

        # Update SKU
        vm.hardware_profile = HardwareProfile(vm_size=target_sku)
        poller = client.virtual_machines.begin_create_or_update(rg, resource_name, vm)
        poller.result(timeout=300)

        return {
            "success":        True,
            "action":         "resize",
            "vm_name":        resource_name,
            "original_sku":   original_sku,
            "new_sku":        target_sku,
            "data_source":    "live",
        }

    except Exception as exc:
        return {"success": False, "action": "resize", "error": str(exc)}


@tool_registry.register(
    name="restart_app_service",
    server="execution",
    description="Restart an Azure App Service — resolves memory leaks and stuck processes",
    requires_approval=True,
    tags=["app-service", "restart", "incident"],
)
async def restart_app_service(
    resource_name: str = "",
    resource_group: str = "",
    **kwargs,
) -> dict:
    if not resource_name:
        return {"success": False, "error": "resource_name is required"}

    try:
        from azure.mgmt.web import WebSiteManagementClient
        from services.azure_account import current_account

        account = current_account()
        client = WebSiteManagementClient(account.credential(), account.subscription_id)
        rg = resource_group
        if not rg:
            return {"success": False, "error": "resource_group is required"}

        client.web_apps.restart(rg, resource_name)

        return {
            "success":       True,
            "action":        "restart",
            "app_name":      resource_name,
            "data_source":   "live",
        }

    except Exception as exc:
        return {"success": False, "action": "restart", "error": str(exc)}


@tool_registry.register(
    name="stop_app_service",
    server="execution",
    description="Stop an Azure App Service",
    requires_approval=True,
    tags=["app-service", "stop", "cost-saving"],
)
async def stop_app_service(resource_name: str = "", resource_group: str = "", **kwargs) -> dict:
    if not all([resource_name, resource_group]):
        return {"success": False, "error": "resource_name and resource_group are required"}
    try:
        from azure.mgmt.web import WebSiteManagementClient
        from services.azure_account import current_account

        account = current_account()
        client = WebSiteManagementClient(account.credential(), account.subscription_id)
        client.web_apps.stop(resource_group, resource_name)
        return {
            "success": True,
            "action": "stop",
            "app_name": resource_name,
            "resource_group": resource_group,
            "data_source": "live",
        }
    except Exception as exc:
        return {"success": False, "action": "stop", "app_name": resource_name, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="start_app_service",
    server="execution",
    description="Start an Azure App Service",
    requires_approval=True,
    tags=["app-service", "start"],
)
async def start_app_service(resource_name: str = "", resource_group: str = "", **kwargs) -> dict:
    if not all([resource_name, resource_group]):
        return {"success": False, "error": "resource_name and resource_group are required"}
    try:
        from azure.mgmt.web import WebSiteManagementClient
        from services.azure_account import current_account

        account = current_account()
        client = WebSiteManagementClient(account.credential(), account.subscription_id)
        client.web_apps.start(resource_group, resource_name)
        return {
            "success": True,
            "action": "start",
            "app_name": resource_name,
            "resource_group": resource_group,
            "data_source": "live",
        }
    except Exception as exc:
        return {"success": False, "action": "start", "app_name": resource_name, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="restore_blob",
    server="execution",
    description="Restore a missing blob asset from backup (e.g. company logo, static assets)",
    requires_approval=True,
    tags=["blob", "restore", "incident", "self-healing"],
)
async def restore_blob(
    container_name: str = "",
    blob_name: str = "",
    backup_source: str = "",
    storage_account: str = "",
    **kwargs,
) -> dict:
    """
    Mentor demo: self-healing website.
    If companylogo.png is missing → restore from backup container.

    Phase 4: Wire to azure.storage.blob SDK copy operations.
    """
    if not all([container_name, blob_name]):
        return {"success": False, "error": "container_name and blob_name required"}

    try:
        from azure.storage.blob import BlobServiceClient
        from services.azure_account import current_account

        acct = storage_account
        if not acct:
            return {"success": False, "error": "storage_account is required"}
        account = current_account()
        url    = f"https://{acct}.blob.core.windows.net"
        client = BlobServiceClient(account_url=url, credential=account.credential())

        # Copy from backup container
        source_container = backup_source or f"{container_name}-backup"
        dest_blob  = client.get_blob_client(container=container_name, blob=blob_name)
        source_url = f"{url}/{source_container}/{blob_name}"
        dest_blob.start_copy_from_url(source_url)

        return {
            "success":    True,
            "action":     "restore",
            "blob_name":  blob_name,
            "container":  container_name,
            "restored_from": source_container,
            "data_source": "live",
        }

    except Exception as exc:
        return {
            "success":  False,
            "action":   "restore",
            "blob_name": blob_name,
            "error":    str(exc),
            "note":     (
                "For demo: the self-healing flow is "
                "CloudOps agent → detect missing asset → Approval Queue → restore_blob"
            ),
        }


@tool_registry.register(
    name="scale_container_app",
    server="execution",
    description="Scale Azure Container App replica count up or down",
    requires_approval=True,
    tags=["container-app", "scale", "performance"],
)
async def scale_container_app(
    resource_name: str = "",
    resource_group: str = "",
    min_replicas: int = 1,
    max_replicas: int = 3,
    **kwargs,
) -> dict:
    if not all([resource_name, resource_group]):
        return {"success": False, "error": "resource_name and resource_group are required"}
    try:
        from azure.mgmt.appcontainers import ContainerAppsAPIClient
        from services.azure_account import current_account

        account = current_account()
        client = ContainerAppsAPIClient(account.credential(), account.subscription_id)
        app = client.container_apps.get(resource_group, resource_name)
        if app.template is None:
            return {"success": False, "error": "Container App template was not returned by Azure."}
        if app.template.scale is None:
            from azure.mgmt.appcontainers.models import Scale
            app.template.scale = Scale()
        app.template.scale.min_replicas = int(min_replicas)
        app.template.scale.max_replicas = int(max_replicas)
        poller = client.container_apps.begin_create_or_update(resource_group, resource_name, app)
        poller.result(timeout=300)
        return {
            "success": True,
            "action": "scale",
            "app_name": resource_name,
            "resource_group": resource_group,
            "min_replicas": int(min_replicas),
            "max_replicas": int(max_replicas),
            "data_source": "live",
        }
    except ImportError:
        return {
            "success": False,
            "action": "scale",
            "app_name": resource_name,
            "data_source": "not_configured",
            "note": "Install azure-mgmt-appcontainers to enable Container Apps scaling.",
        }
    except Exception as exc:
        return {"success": False, "action": "scale", "app_name": resource_name, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="delete_resource",
    server="execution",
    description="Delete a selected Azure resource by ARM resource ID",
    requires_approval=True,
    tags=["delete", "resource", "destructive"],
)
async def delete_resource(
    resource_id: str = "",
    resource_name: str = "",
    api_version: str = "",
    **kwargs,
) -> dict:
    if not resource_id:
        return {
            "success": False,
            "action": "delete",
            "resource_name": resource_name,
            "error": "resource_id is required for safe generic deletion",
        }

    try:
        response = await _management_request(
            "DELETE",
            resource_id,
            api_version or _api_version_for_resource_id(resource_id),
        )
        return {
            "success": response["ok"],
            "action": "delete",
            "resource_id": resource_id,
            "resource_name": resource_name or resource_id.rstrip("/").split("/")[-1],
            "status_code": response["status_code"],
            "operation_url": response.get("operation_url"),
            "data_source": "live",
            "note": "Azure accepted the delete operation." if response["ok"] else response.get("text", ""),
        }
    except Exception as exc:
        return {"success": False, "action": "delete", "resource_id": resource_id, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="create_resource_group",
    server="execution",
    description="Create an Azure resource group",
    requires_approval=True,
    tags=["create", "resource-group"],
)
async def create_resource_group(
    resource_name: str = "",
    resource_group: str = "",
    location: str = "eastus",
    **kwargs,
) -> dict:
    name = resource_group or resource_name
    if not name:
        return {"success": False, "action": "create_resource_group", "error": "resource_group or resource_name is required"}

    try:
        from services.azure_account import current_account

        account = current_account()
        path = f"/subscriptions/{account.subscription_id}/resourcegroups/{name}"
        response = await _management_request(
            "PUT",
            path,
            "2021-04-01",
            json_body={"location": location},
        )
        return {
            "success": response["ok"],
            "action": "create_resource_group",
            "resource_group": name,
            "location": location,
            "status_code": response["status_code"],
            "data_source": "live",
            "note": "Resource group created or updated." if response["ok"] else response.get("text", ""),
        }
    except Exception as exc:
        return {"success": False, "action": "create_resource_group", "resource_group": name, "data_source": "error", "error": str(exc)}


@tool_registry.register(
    name="create_storage_account",
    server="execution",
    description="Create a general-purpose v2 Azure Storage account",
    requires_approval=True,
    tags=["create", "storage"],
)
async def create_storage_account(
    resource_name: str = "",
    resource_group: str = "",
    location: str = "eastus",
    sku: str = "Standard_LRS",
    **kwargs,
) -> dict:
    if not all([resource_name, resource_group]):
        return {"success": False, "action": "create_storage_account", "error": "resource_name and resource_group are required"}

    try:
        from services.azure_account import current_account

        account = current_account()
        path = (
            f"/subscriptions/{account.subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Storage/storageAccounts/{resource_name}"
        )
        response = await _management_request(
            "PUT",
            path,
            "2023-01-01",
            json_body={
                "sku": {"name": sku},
                "kind": "StorageV2",
                "location": location,
                "properties": {"accessTier": "Hot", "allowBlobPublicAccess": False},
            },
        )
        return {
            "success": response["ok"],
            "action": "create_storage_account",
            "storage_account": resource_name,
            "resource_group": resource_group,
            "location": location,
            "sku": sku,
            "status_code": response["status_code"],
            "operation_url": response.get("operation_url"),
            "data_source": "live",
            "note": "Azure accepted the storage account deployment." if response["ok"] else response.get("text", ""),
        }
    except Exception as exc:
        return {"success": False, "action": "create_storage_account", "storage_account": resource_name, "data_source": "error", "error": str(exc)}


def _api_version_for_resource_id(resource_id: str) -> str:
    lowered = resource_id.lower()
    versions = {
        "microsoft.compute/virtualmachines": "2023-09-01",
        "microsoft.web/sites": "2023-12-01",
        "microsoft.app/containerapps": "2023-05-01",
        "microsoft.storage/storageaccounts": "2023-01-01",
        "microsoft.keyvault/vaults": "2023-07-01",
        "microsoft.search/searchservices": "2023-11-01",
        "microsoft.containerregistry/registries": "2023-01-01-preview",
    }
    for resource_type, version in versions.items():
        if resource_type in lowered:
            return version
    return "2021-04-01"


async def _management_request(
    method: str,
    path: str,
    api_version: str,
    json_body: dict | None = None,
) -> dict:
    import httpx
    from services.azure_account import current_account

    account = current_account()
    token = account.credential().get_token("https://management.azure.com/.default").token
    url = path if path.startswith("https://") else f"https://management.azure.com{path}"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            method,
            url,
            params={"api-version": api_version},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body,
        )
    text = response.text[:1200] if response.text else ""
    return {
        "ok": response.status_code in {200, 201, 202, 204},
        "status_code": response.status_code,
        "text": text,
        "operation_url": response.headers.get("azure-asyncoperation") or response.headers.get("location"),
    }
