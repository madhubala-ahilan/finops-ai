"""
mcp/cloudops_server/tools.py — CloudOps MCP Server

Tools:
  get_resource_inventory()   → All Azure resources via Resource Graph
  get_resource_health()      → Health states across subscription
  query_monitor_metrics()    → CPU/memory/egress for a resource
  check_blob_asset()         → Check if a file exists in Blob Storage
  get_app_insights_errors()  → Application errors + failures

Used by:
  CloudOps agent, Incident agent
"""

from mcp_layer.tool_registry import tool_registry


@tool_registry.register(
    name="get_resource_inventory",
    server="cloudops",
    description="Full Azure resource inventory from Resource Graph (FREE API)",
    tags=["resources", "inventory", "resource-graph"],
)
async def get_resource_inventory(**kwargs) -> dict:
    from services.azure_resource_service import get_all_resources
    return await get_all_resources()


@tool_registry.register(
    name="get_resource_health",
    server="cloudops",
    description="Azure Resource Health: availability states across subscription",
    tags=["health", "availability", "resource-health"],
)
async def get_resource_health(**kwargs) -> dict:
    from services.azure_resource_service import get_resource_health_summary
    return await get_resource_health_summary()


@tool_registry.register(
    name="query_monitor_metrics",
    server="cloudops",
    description="Azure Monitor metrics (CPU, memory, egress) for a specific resource",
    tags=["metrics", "monitor", "cpu", "memory"],
)
async def query_monitor_metrics(
    resource_id: str = "",
    metric_names: list = None,
    lookback_hours: int = 24,
    **kwargs,
) -> dict:
    from services.azure_monitor_service import get_resource_metrics

    if not resource_id:
        return {
            "error": "resource_id is required",
            "example": "/subscriptions/{sub}/resourceGroups/{rg}/providers/..."
        }

    metrics = metric_names or ["Percentage CPU", "Network In Total", "Network Out Total"]
    return await get_resource_metrics(
        resource_id=resource_id,
        metric_names=metrics,
        lookback_hours=int(lookback_hours),
    )


@tool_registry.register(
    name="query_log_analytics",
    server="cloudops",
    description="Run a Kusto query against the configured Log Analytics workspace",
    tags=["log-analytics", "kusto", "logs"],
)
async def query_log_analytics_tool(query: str = "", timespan_hours: int = 24, **kwargs) -> dict:
    from services.azure_monitor_service import query_log_analytics

    if not query:
        return {"rows": [], "data_source": "empty", "error": "query is required"}
    return await query_log_analytics(query=query, timespan_hours=int(timespan_hours))


@tool_registry.register(
    name="get_policy_compliance",
    server="cloudops",
    description="Azure Policy non-compliance summary from Policy Insights",
    tags=["policy", "compliance", "security", "rbac"],
)
async def get_policy_compliance(**kwargs) -> dict:
    from services.azure_policy_service import get_policy_compliance_summary
    return await get_policy_compliance_summary()


@tool_registry.register(
    name="check_blob_asset",
    server="cloudops",
    description="Check if a file/asset exists in Azure Blob Storage and get its metadata",
    tags=["blob", "storage", "assets", "incident"],
)
async def check_blob_asset(
    container_name: str = "",
    blob_name: str = "",
    storage_account: str = "",
    **kwargs,
) -> dict:
    """
    CloudOps mentor demo:
      check_blob_asset(container_name="web-assets", blob_name="companylogo.png")

    Returns: exists (bool), size, last_modified, metadata.
    """
    try:
        from azure.storage.blob import BlobServiceClient
        from config import settings
        from services.azure_account import current_account

        acct  = storage_account or getattr(settings, "AZURE_STORAGE_ACCOUNT", "")
        if not acct:
            raise ValueError("No storage account configured")

        cred   = current_account().credential()
        url    = f"https://{acct}.blob.core.windows.net"
        client = BlobServiceClient(account_url=url, credential=cred)
        blob   = client.get_blob_client(container=container_name, blob=blob_name)
        props  = blob.get_blob_properties()

        return {
            "exists":        True,
            "blob_name":     blob_name,
            "container":     container_name,
            "size_bytes":    props.size,
            "last_modified": str(props.last_modified),
            "content_type":  props.content_settings.content_type,
            "data_source":   "live",
        }

    except Exception as exc:
        is_missing = "not found" in str(exc).lower() or "BlobNotFound" in str(exc)
        return {
            "exists":      False if is_missing else None,
            "blob_name":   blob_name,
            "container":   container_name,
            "error":       str(exc),
            "data_source": "error",
            "recommended_action": (
                f"Asset '{blob_name}' not found in '{container_name}'. "
                "Use execution/restore_blob tool to restore from backup."
            ) if is_missing else None,
        }


@tool_registry.register(
    name="get_app_insights_errors",
    server="cloudops",
    description="Application Insights error rate and failed requests for an application",
    tags=["app-insights", "errors", "telemetry", "incident"],
)
async def get_app_insights_errors(
    app_name: str = "",
    lookback_hours: int = 1,
    **kwargs,
) -> dict:
    from config import settings
    from services.azure_monitor_service import query_log_analytics

    if getattr(settings, "LOG_ANALYTICS_WORKSPACE_ID", ""):
        query = """
AppRequests
| where TimeGenerated > ago(24h)
| summarize failed_requests=countif(Success == false), total=count(), avg_duration_ms=avg(DurationMs)
"""
        result = await query_log_analytics(query=query, timespan_hours=int(lookback_hours))
        return {
            "app_name": app_name,
            "lookback_hours": lookback_hours,
            "data_source": result.get("data_source"),
            "rows": result.get("rows", []),
            "note": result.get("note"),
            "error": result.get("error"),
        }
    return {
        "app_name": app_name,
        "lookback_hours": lookback_hours,
        "data_source": "not_configured",
        "note": "Configure LOG_ANALYTICS_WORKSPACE_ID to query Application Insights logs.",
    }


@tool_registry.register(
    name="get_incident_summary",
    server="cloudops",
    description="Active incidents: failed resources, service outages, blob issues",
    tags=["incident", "health", "outage"],
)
async def get_incident_summary(**kwargs) -> dict:
    from services.azure_resource_service import get_resource_health_summary
    health = await get_resource_health_summary()
    return {
        "unavailable_resources": health.get("unavailable", 0),
        "degraded_resources":    health.get("degraded", 0),
        "active_incidents":      health.get("unavailable", 0) + health.get("degraded", 0),
        "health_summary":        health,
        "data_source":           health.get("data_source", "unknown"),
    }
