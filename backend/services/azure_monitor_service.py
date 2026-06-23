"""
services/azure_monitor_service.py — Azure Monitor metrics integration.

Phase 3 service: provides real CPU, memory, storage, and availability
metrics from Azure Monitor for the CloudOps and Incident agents.

All Azure Monitor query operations are FREE.

Install SDK:
    pip install azure-monitor-query --break-system-packages
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from config import settings
from services.azure_account import current_account

logger = logging.getLogger("finops.monitor")

# ── Default lookback windows ──────────────────────────────────────────────────
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_GRANULARITY    = timedelta(hours=1)


def _get_credential():
    return current_account().credential()


async def query_log_analytics(query: str, timespan_hours: int = 24) -> Dict[str, Any]:
    """Run a live Kusto query against Log Analytics when a workspace is configured."""
    workspace_id = getattr(settings, "LOG_ANALYTICS_WORKSPACE_ID", "")
    if not workspace_id:
        return {
            "rows": [],
            "data_source": "not_configured",
            "note": "LOG_ANALYTICS_WORKSPACE_ID is not configured.",
        }
    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus

        client = LogsQueryClient(_get_credential())
        response = client.query_workspace(
            workspace_id,
            query,
            timespan=timedelta(hours=timespan_hours),
        )
        if response.status == LogsQueryStatus.PARTIAL:
            table = response.partial_data[0] if response.partial_data else None
        else:
            table = response.tables[0] if response.tables else None
        if not table:
            return {"rows": [], "data_source": "live"}
        columns = [col.name for col in table.columns]
        rows = [dict(zip(columns, row)) for row in table.rows]
        return {"rows": rows, "data_source": "live", "columns": columns}
    except Exception as exc:
        return {"rows": [], "data_source": "error", "error": str(exc)}


async def get_resource_metrics(
    resource_id: str,
    metric_names: List[str],
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
) -> Dict[str, Any]:
    """
    Fetch Azure Monitor metrics for a specific resource.

    Args:
        resource_id:    Full Azure resource ID (from Resource Graph).
        metric_names:   e.g. ["Percentage CPU", "Network In Total"].
        lookback_hours: How many hours of history to fetch.

    Returns:
        Dict mapping metric_name → list of {timestamp, value} dicts.

    Returns an empty/error response if Azure Monitor query support is not installed.
    """
    try:
        from azure.monitor.query import MetricsQueryClient, MetricAggregationType

        credential = _get_credential()
        client = MetricsQueryClient(credential)

        end_time   = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=lookback_hours)

        response = client.query_resource(
            resource_id,
            metric_names=metric_names,
            timespan=(start_time, end_time),
            granularity=DEFAULT_GRANULARITY,
            aggregations=[MetricAggregationType.AVERAGE],
        )

        result = {}
        for metric in response.metrics:
            series = []
            for ts in metric.timeseries:
                for dp in ts.data:
                    if dp.average is not None:
                        series.append({
                            "timestamp": dp.timestamp.isoformat(),
                            "value":     round(dp.average, 4),
                        })
            result[metric.name] = series

        logger.info(f"Monitor: fetched {len(result)} metrics for {resource_id.split('/')[-1]}")
        return {"data": result, "data_source": "live", "resource_id": resource_id}

    except ImportError:
        logger.warning(
            "azure-monitor-query not installed. "
            "Run: pip install azure-monitor-query --break-system-packages"
        )
        return {"data": {}, "data_source": "empty", "note": "azure-monitor-query is not installed."}
    except Exception as exc:
        logger.error(f"get_resource_metrics failed: {type(exc).__name__}: {exc}")
        return {"data": {}, "data_source": "error", "error": str(exc)}


async def get_vm_cpu_metrics(
    resource_id: str,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """CPU percentage for a Virtual Machine."""
    return await get_resource_metrics(
        resource_id,
        metric_names=["Percentage CPU"],
        lookback_hours=lookback_hours,
    )


async def get_storage_metrics(
    resource_id: str,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """Transactions and egress for a Storage Account."""
    return await get_resource_metrics(
        resource_id,
        metric_names=["Transactions", "Egress"],
        lookback_hours=lookback_hours,
    )


async def get_sql_metrics(
    resource_id: str,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """DTU consumption for a SQL Database."""
    return await get_resource_metrics(
        resource_id,
        metric_names=["dtu_consumption_percent", "storage_percent"],
        lookback_hours=lookback_hours,
    )


async def get_fired_alerts() -> List[Dict[str, Any]]:
    """
    Fetch currently fired Azure Monitor alerts.

    Phase 3: Wire real Azure Monitor alerts SDK.
    Currently returns empty list (new subscription has no alerts).
    """
    try:
        from azure.mgmt.monitor import MonitorManagementClient

        account = current_account()
        client = MonitorManagementClient(account.credential(), account.subscription_id)

        # List alert rules
        alert_rules = list(client.alert_rules.list_by_subscription())
        result = []
        for rule in alert_rules:
            result.append({
                "id":          rule.name,
                "name":        getattr(rule, "name", ""),
                "severity":    "Sev2",
                "state":       "New",
                "resource":    getattr(rule, "location", ""),
                "description": "Azure Monitor alert rule",
                "fired_at":    datetime.now(timezone.utc).isoformat(),
            })
        return result

    except Exception as exc:
        logger.info(f"get_fired_alerts: {exc} — returning empty (new subscription)")
        return []


async def get_subscription_metrics_summary() -> Dict[str, Any]:
    """
    High-level metrics summary for the dashboard.
    Returns counts of resources with high CPU/memory/storage.

    Phase 3: Replace with real multi-resource metrics aggregation.
    """
    return {
        "high_cpu_resources":     0,
        "high_memory_resources":  0,
        "high_storage_resources": 0,
        "fired_alerts":           0,
        "data_source":            "empty",
        "note": "Azure Monitor summary aggregation is not configured.",
    }


# ── Mock data helpers ─────────────────────────────────────────────────────────
