"""
AzureResourceService — Real Azure Resource Graph + Resource Health queries.

FIXES applied:
  1. Advisor: 'ResourceRecommendationBase' has no .properties — attributes
     are accessed directly on the object in azure-mgmt-advisor 9.x SDK.
  2. Health: MicrosoftResourceHealth → ResourceHealthMgmtClient (already applied).
  3. Added safe attribute helper _safe() to prevent AttributeError cascades.

Resource Graph queries are FREE on Azure (no per-call charge).
Resource Health is also FREE.
"""

from azure.identity import ClientSecretCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest
from azure.mgmt.resourcehealth import ResourceHealthMgmtClient
from config import settings
from services.azure_account import AzureAccount, current_account
import logging

logger = logging.getLogger("finops.resources")


def _get_credential(account: AzureAccount | None = None) -> ClientSecretCredential:
    account = account or current_account()
    return account.credential()


def _safe(obj, *attrs, default=None):
    """Safely chain attribute access — returns default if any attr is missing."""
    for attr in attrs:
        if obj is None:
            return default
        obj = getattr(obj, attr, None)
    return obj if obj is not None else default


async def get_all_resources(account: AzureAccount | None = None) -> dict:
    """
    Queries Azure Resource Graph for all resources in the subscription.
    Resource Graph API is FREE.
    """
    try:
        account = account or current_account()
        if not account.configured:
            return {
                "total": 0, "healthy": 0, "warning": 0, "critical": 0, "unknown": 0,
                "resources": [], "data_source": "empty", "note": "Azure account is not connected.",
            }

        credential = _get_credential(account)
        rg_client = ResourceGraphClient(credential)

        query = QueryRequest(
            subscriptions=[account.subscription_id],
            query="""
            Resources
            | where subscriptionId == '{sub}'
            | project
                name,
                type,
                location,
                resourceGroup,
                tags,
                id,
                kind,
                properties
            | order by type asc, name asc
            | limit 200
            """.replace("{sub}", account.subscription_id),
        )

        result = rg_client.resources(query)
        raw_resources = result.data or []

        type_map = {
            "microsoft.compute/virtualmachines":          "Virtual Machine",
            "microsoft.sql/servers/databases":            "SQL Database",
            "microsoft.web/sites":                        "App Service",
            "microsoft.storage/storageaccounts":          "Storage Account",
            "microsoft.keyvault/vaults":                  "Key Vault",
            "microsoft.containerservice/managedclusters": "AKS Cluster",
            "microsoft.search/searchservices":            "AI Search",
            "microsoft.cognitiveservices/accounts":       "Azure OpenAI / Cognitive",
            "microsoft.operationalinsights/workspaces":   "Log Analytics",
            "microsoft.containerregistry/registries":     "Container Registry",
            "microsoft.network/virtualnetworks":          "Virtual Network",
            "microsoft.network/networksecuritygroups":    "NSG",
            "microsoft.insights/components":              "App Insights",
        }

        resources = []
        for r in raw_resources:
            raw_type = r.get("type", "").lower()
            friendly_type = type_map.get(raw_type, r.get("type", "Unknown"))
            properties = r.get("properties") or {}
            status = _derive_resource_status(raw_type, properties)
            resources.append({
                "name":           r.get("name", ""),
                "type":           friendly_type,
                "raw_type":       r.get("type", ""),
                "region":         r.get("location", ""),
                "resource_group": r.get("resourceGroup", ""),
                "id":             r.get("id", ""),
                "status":         status,
                "cost_monthly":   0,
            })

        healthy_statuses = {"running", "available", "succeeded", "ready", "online", "enabled"}
        stopped_statuses = {"stopped", "deallocated", "stoppeddeallocated", "unavailable", "failed"}
        healthy = sum(1 for item in resources if _normalise_status(item.get("status")) in healthy_statuses)
        critical = sum(1 for item in resources if _normalise_status(item.get("status")) in stopped_statuses)
        unknown = sum(1 for item in resources if _normalise_status(item.get("status")) == "unknown")

        return {
            "total":     len(resources),
            "healthy":   healthy,
            "warning":   max(0, len(resources) - healthy - critical - unknown),
            "critical":  critical,
            "unknown":   unknown,
            "resources": resources,
            "data_source": "live",
        }

    except Exception as exc:
        logger.error(f"AzureResourceService.get_all_resources failed: {type(exc).__name__}: {exc}")
        return {
            "total": 0, "healthy": 0, "warning": 0, "critical": 0, "unknown": 0,
            "resources": [], "data_source": "error", "error": str(exc),
        }


async def get_resource_health_summary(account: AzureAccount | None = None) -> dict:
    """
    Azure Resource Health API (FREE) — availability state summary.
    """
    try:
        account = account or current_account()
        if not account.configured:
            return {"total": 0, "available": 0, "unavailable": 0, "degraded": 0, "unknown": 0, "data_source": "empty", "note": "Azure account is not connected."}

        credential = _get_credential(account)
        health_client = ResourceHealthMgmtClient(credential, account.subscription_id)

        events = list(health_client.availability_statuses.list_by_subscription_id())

        available   = sum(1 for e in events if _safe(e, "properties", "availability_state") == "Available")
        unavailable = sum(1 for e in events if _safe(e, "properties", "availability_state") == "Unavailable")
        degraded    = sum(1 for e in events if _safe(e, "properties", "availability_state") == "Degraded")
        unknown_cnt = len(events) - available - unavailable - degraded

        return {
            "total":       len(events),
            "available":   available,
            "unavailable": unavailable,
            "degraded":    degraded,
            "unknown":     unknown_cnt,
            "data_source": "live",
        }

    except Exception as exc:
        logger.error(f"get_resource_health_summary failed: {type(exc).__name__}: {exc}")
        return {"data_source": "error", "error": str(exc)}


async def get_advisor_recommendations(account: AzureAccount | None = None) -> list:
    """
    Azure Advisor recommendations — FREE API.

    FIX: azure-mgmt-advisor 9.x SDK exposes attributes DIRECTLY on
    ResourceRecommendationBase, NOT under a nested .properties object.

    Corrected attribute access:
      r.category                             (was: r.properties.category)
      r.impact                               (was: r.properties.impact)
      r.short_description.solution           (was: r.properties.short_description.solution)
      r.resource_metadata.resource_id        (was: r.properties.resource_metadata.resource_id)
      r.extended_properties.annualSavingsAmount  (unchanged — dict access)
    """
    try:
        from azure.mgmt.advisor import AdvisorManagementClient
        account = account or current_account()
        if not account.configured:
            return []

        credential = _get_credential(account)
        advisor_client = AdvisorManagementClient(credential, account.subscription_id)

        recs = list(advisor_client.recommendations.list())
        result = []
        for r in recs:
            # ── Direct attribute access (SDK 9.x) ─────────────────────────────
            category      = _safe(r, "category", default="")
            impact        = _safe(r, "impact",   default="")
            resource_id   = _safe(r, "resource_metadata", "resource_id", default="")
            solution      = _safe(r, "short_description", "solution",    default="")
            problem       = _safe(r, "short_description", "problem",     default="")

            # extended_properties is a plain dict in 9.x
            ext_props = getattr(r, "extended_properties", None) or {}
            savings = ext_props.get("annualSavingsAmount") if isinstance(ext_props, dict) else None

            result.append({
                "id":                r.name,
                "category":          category,
                "impact":            impact,
                "resource":          resource_id,
                "short_description": solution,
                "problem":           problem,
                "potential_savings": savings,
            })

        logger.info(f"Advisor returned {len(result)} recommendations")
        return result

    except Exception as exc:
        logger.error(f"get_advisor_recommendations failed: {type(exc).__name__}: {exc}")
        return []


def _derive_resource_status(raw_type: str, properties: dict) -> str:
    raw_type = str(raw_type or "").lower()
    properties = properties or {}
    if raw_type == "microsoft.compute/virtualmachines":
        instance_view = properties.get("extended", {}).get("instanceView", {}) if isinstance(properties.get("extended"), dict) else {}
        power_state = instance_view.get("powerState") if isinstance(instance_view, dict) else None
        if isinstance(power_state, dict):
            display = power_state.get("displayStatus") or power_state.get("code")
            if display:
                return _clean_status(display)
        statuses = instance_view.get("statuses", []) if isinstance(instance_view, dict) else []
        for status in statuses or []:
            code = str((status or {}).get("code") or "")
            display = str((status or {}).get("displayStatus") or "")
            if code.lower().startswith("powerstate/") or display.lower().startswith("vm "):
                return _clean_status(display or code)
    if raw_type == "microsoft.web/sites":
        return _clean_status(properties.get("state") or properties.get("availabilityState") or properties.get("provisioningState") or "unknown")
    if raw_type == "microsoft.app/containerapps":
        return _clean_status(properties.get("runningStatus") or properties.get("provisioningState") or "unknown")
    if raw_type == "microsoft.storage/storageaccounts":
        return _clean_status(properties.get("statusOfPrimary") or properties.get("provisioningState") or "unknown")
    return _clean_status(properties.get("provisioningState") or properties.get("status") or properties.get("state") or "unknown")


def _clean_status(value: str) -> str:
    text = str(value or "unknown").strip()
    if not text:
        return "unknown"
    text = text.replace("PowerState/", "").replace("powerstate/", "")
    text = text.replace("VM ", "")
    return text[:1].upper() + text[1:]


def _normalise_status(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "unknown") if ch.isalnum()) or "unknown"
