"""Live Azure Cost Management access with throttling protection.

The dashboard, anomaly detector, forecast endpoint, and chat tools all need the
same month-to-date cost shape. Azure Cost Management throttles quickly on small
subscriptions, so this module intentionally uses one grouped query and caches the
live response for a short period instead of firing multiple independent queries.
"""

from __future__ import annotations

import copy
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from azure.core.exceptions import HttpResponseError
from azure.identity import ClientSecretCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    GranularityType,
    QueryAggregation,
    QueryDataset,
    QueryDefinition,
    QueryGrouping,
    QueryTimePeriod,
    TimeframeType,
)

from services.azure_account import AzureAccount, current_account

try:
    from config import settings
except ImportError:
    class _Settings:
        AZURE_TENANT_ID = ""
        AZURE_CLIENT_ID = ""
        AZURE_CLIENT_SECRET = ""
        AZURE_SUBSCRIPTION_ID = ""
        COST_BUDGET_MONTHLY_USD = 500.0

    settings = _Settings()

logger = logging.getLogger("finops.cost")

_CACHE_TTL = timedelta(seconds=getattr(settings, "COST_CACHE_TTL_SECONDS", 900))
_NEGATIVE_CACHE_TTL = timedelta(seconds=60)
_SUMMARY_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
_SUMMARY_LOCKS: dict[str, asyncio.Lock] = {}
_STATE_PATH = Path(getattr(settings, "FINOPS_STATE_FILE", "finops_state.json"))

_BILLING_NOT_READY_CODES = {
    "BillingAccountNotFound",
    "IndirectCostDisabled",
    "Unauthorized",
    "BudgetOperationNotSupported",
    "OfferNotSupported",
    "BillingRequestFailed",
}

_BILLING_NOT_READY_MSGS = (
    "billing data not available",
    "does not have any offer",
    "indirect cost",
    "offer not supported",
    "ea enrollment",
    "billing account",
    "free trial",
    "azure for students",
    "cost management only supports",
)


def _is_billing_not_ready(exc: HttpResponseError) -> bool:
    error = getattr(exc, "error", None)
    if error:
        code = getattr(error, "code", "") or ""
        if code in _BILLING_NOT_READY_CODES:
            return True
    message = str(exc).lower()
    return any(text in message for text in _BILLING_NOT_READY_MSGS)


def _is_throttled(exc: HttpResponseError) -> bool:
    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    error = getattr(exc, "error", None)
    code = str(getattr(error, "code", "") or "")
    return status_code == 429 or code == "429" or "too many requests" in str(exc).lower()


def _credential(account: AzureAccount | None = None) -> ClientSecretCredential:
    account = account or current_account()
    return account.credential()


def _client(account: AzureAccount | None = None) -> CostManagementClient:
    return CostManagementClient(_credential(account))


def _scope(account: AzureAccount | None = None) -> str:
    account = account or current_account()
    return f"/subscriptions/{account.subscription_id}"


def _cache_key(account: AzureAccount) -> str:
    return account.subscription_id.lower()


def _summary_lock(account: AzureAccount) -> asyncio.Lock:
    return _SUMMARY_LOCKS.setdefault(_cache_key(account), asyncio.Lock())


def _load_persisted_cost_cache() -> None:
    try:
        if _SUMMARY_CACHE or not _STATE_PATH.exists():
            return
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        cost_cache = data.get("cost_cache", {})
        if not isinstance(cost_cache, dict):
            return
        for key, entry in cost_cache.items():
            fetched_at = datetime.fromisoformat(entry["fetched_at"])
            payload = entry["payload"]
            if isinstance(payload, dict):
                _SUMMARY_CACHE[key] = (fetched_at, payload)
    except Exception as exc:
        logger.warning("Could not load persisted cost cache from %s: %s", _STATE_PATH, exc)


def _persist_cost_cache() -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        data["cost_cache"] = {
            key: {
                "fetched_at": fetched_at.isoformat(),
                "payload": payload,
            }
            for key, (fetched_at, payload) in _SUMMARY_CACHE.items()
        }
        _STATE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist cost cache to %s: %s", _STATE_PATH, exc)


def _cached_summary(account: AzureAccount, allow_stale: bool = False) -> dict[str, Any] | None:
    _load_persisted_cost_cache()
    cached = _SUMMARY_CACHE.get(_cache_key(account))
    if not cached:
        return None

    fetched_at, payload = cached
    age = datetime.now(timezone.utc) - fetched_at
    if payload.get("data_source") in {"throttled", "error"} and age > _NEGATIVE_CACHE_TTL:
        return None
    if not allow_stale and age > _CACHE_TTL:
        return None

    result = copy.deepcopy(payload)
    if result.get("data_source") == "consumption_usage_details":
        result["note"] = "Live Azure Consumption usageDetails."
        result.setdefault(
            "upstream_note",
            "Cost Management Query was throttled, so the app used live Azure Consumption usageDetails instead.",
        )
    result["cached"] = True
    result["cache_age_seconds"] = int(age.total_seconds())
    return result


def _store_summary(account: AzureAccount, payload: dict[str, Any]) -> dict[str, Any]:
    stored = copy.deepcopy(payload)
    stored["cached"] = False
    stored["cache_ttl_seconds"] = int(_CACHE_TTL.total_seconds())
    _SUMMARY_CACHE[_cache_key(account)] = (datetime.now(timezone.utc), stored)
    _persist_cost_cache()
    return copy.deepcopy(stored)


def _rows(result: Any) -> list[list[Any]]:
    rows = getattr(result, "rows", None)
    return rows if rows else []


def _columns(result: Any) -> list[str]:
    columns = getattr(result, "columns", None) or []
    names: list[str] = []
    for column in columns:
        names.append(str(getattr(column, "name", None) or getattr(column, "column_name", None) or column))
    return names


def _column_index(columns: list[str], names: tuple[str, ...], default: int | None = None) -> int | None:
    lowered = [column.lower() for column in columns]
    for expected in names:
        expected_lower = expected.lower()
        for index, column in enumerate(lowered):
            if column == expected_lower or expected_lower in column:
                return index
    return default


def _date_key(raw: Any) -> tuple[str, str]:
    value = str(raw)
    if value.isdigit() and len(value) == 8:
        return value, f"{value[4:6]}/{value[6:8]}"
    if len(value) >= 10:
        return value[:10], value[5:10]
    return value, value


def _fallback(note: str, error: str | None = None, data_source: str = "empty") -> dict[str, Any]:
    logger.info("Cost Management: %s Returning clean fallback.", note)
    return {
        "mtd_spend": 0.0,
        "last_month_spend": None,
        "budget_monthly": settings.COST_BUDGET_MONTHLY_USD,
        "budget_utilisation_pct": 0.0,
        "trend": [],
        "by_service": {},
        "currency": "USD",
        "data_source": data_source,
        "note": note,
        "error": error,
        "cached": False,
        "cache_ttl_seconds": int(_CACHE_TTL.total_seconds()),
    }


def _float_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _usage_details_summary(account: AzureAccount, first: datetime, now: datetime) -> dict[str, Any] | None:
    """Fallback to the live Consumption Usage Details API when Query API is throttled."""
    token = _credential(account).get_token("https://management.azure.com/.default").token
    url = (
        "https://management.azure.com"
        f"/subscriptions/{account.subscription_id}/providers/Microsoft.Consumption/usageDetails"
    )
    params: dict[str, str] | None = {
        "api-version": "2023-05-01",
        "$top": "1000",
        "$filter": (
            f"properties/usageStart ge '{first.date().isoformat()}' "
            f"and properties/usageEnd le '{now.date().isoformat()}'"
        ),
    }
    items: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=25) as client:
        while url and len(items) < 3000:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if response.status_code == 429:
                logger.info("Consumption usageDetails fallback is also throttled.")
                return None
            response.raise_for_status()
            data = response.json()
            values = data.get("value") or []
            if isinstance(values, list):
                items.extend(item for item in values if isinstance(item, dict))
            url = data.get("nextLink")
            params = None

    if not items:
        return {
            "mtd_spend": 0.0,
            "last_month_spend": None,
            "budget_monthly": settings.COST_BUDGET_MONTHLY_USD,
            "budget_utilisation_pct": 0.0,
            "trend": [],
            "by_service": {},
            "currency": "USD",
            "data_source": "consumption_usage_details",
            "note": "Azure Consumption usageDetails returned no charge rows for this month yet.",
            "error": None,
        }

    daily: dict[str, dict[str, Any]] = {}
    by_service: dict[str, float] = {}
    currency = "USD"

    for item in items:
        props = item.get("properties") or item
        if not isinstance(props, dict):
            continue
        amount = _float_value(
            props.get("costInBillingCurrency")
            or props.get("pretaxCost")
            or props.get("cost")
            or props.get("extendedCost")
        )
        if amount == 0:
            continue

        raw_date = props.get("date") or props.get("usageStart") or props.get("usageStartDate")
        if raw_date:
            sort_key, label = _date_key(raw_date)
            daily.setdefault(sort_key, {"date": label, "amount": 0.0})
            daily[sort_key]["amount"] += amount

        service = (
            props.get("consumedService")
            or props.get("meterCategory")
            or props.get("serviceName")
            or props.get("product")
            or "Other"
        )
        by_service[str(service)] = by_service.get(str(service), 0.0) + amount
        currency = str(props.get("billingCurrency") or props.get("currency") or props.get("currencyCode") or currency)

    trend = [
        {"date": value["date"], "amount": round(float(value["amount"]), 2)}
        for _, value in sorted(daily.items(), key=lambda item: item[0])
    ]
    services = {
        name: round(amount, 2)
        for name, amount in sorted(by_service.items(), key=lambda item: item[1], reverse=True)
        if amount
    }
    mtd_spend = round(sum(item["amount"] for item in trend), 2)
    budget = settings.COST_BUDGET_MONTHLY_USD
    logger.info("Cost summary OK from usageDetails: rows=%s MTD=%s%.2f", len(items), currency, mtd_spend)
    return {
        "mtd_spend": mtd_spend,
        "last_month_spend": None,
        "budget_monthly": budget,
        "budget_utilisation_pct": round((mtd_spend / budget) * 100, 1) if budget else 0.0,
        "trend": trend,
        "by_service": services,
        "currency": currency,
        "data_source": "consumption_usage_details",
        "note": "Live Azure Consumption usageDetails.",
        "upstream_note": "Cost Management Query was throttled, so the app used live Azure Consumption usageDetails instead.",
        "error": None,
    }


async def get_mtd_summary(account: AzureAccount | None = None) -> dict[str, Any]:
    """Return MTD spend, daily trend, and service breakdown from live Azure data."""
    account = account or current_account()
    if not account.configured:
        return _fallback("Azure account is not connected.")

    cached = _cached_summary(account)
    if cached:
        return cached

    async with _summary_lock(account):
        cached = _cached_summary(account)
        if cached:
            return cached
        return await _fetch_mtd_summary(account)


async def _fetch_mtd_summary(account: AzureAccount) -> dict[str, Any]:
    """Fetch a fresh summary from Azure and store the result in the shared cache."""
    now = datetime.now(timezone.utc)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        result = _client(account).query.usage(
            _scope(account),
            QueryDefinition(
                type="ActualCost",
                timeframe=TimeframeType.CUSTOM,
                time_period=QueryTimePeriod(from_property=first, to=now),
                dataset=QueryDataset(
                    granularity=GranularityType.DAILY,
                    aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                    grouping=[QueryGrouping(type="Dimension", name="ServiceName")],
                ),
            ),
        )

        rows = _rows(result)
        columns = _columns(result)
        cost_idx = _column_index(columns, ("cost", "totalcost", "pretaxcost"), 0) or 0
        date_idx = _column_index(columns, ("usagedate", "date"), 1)
        service_idx = _column_index(columns, ("servicename", "service"), 2)
        currency_idx = _column_index(columns, ("currency",), 3)

        daily: dict[str, dict[str, Any]] = {}
        by_service: dict[str, float] = {}
        currency = "USD"

        for row in rows:
            if len(row) <= cost_idx:
                continue
            amount = float(row[cost_idx] or 0)
            if date_idx is not None and len(row) > date_idx:
                sort_key, label = _date_key(row[date_idx])
                daily.setdefault(sort_key, {"date": label, "amount": 0.0})
                daily[sort_key]["amount"] += amount

            service = "Other"
            if service_idx is not None and len(row) > service_idx and row[service_idx]:
                service = str(row[service_idx])
            by_service[service] = by_service.get(service, 0.0) + amount

            if currency_idx is not None and len(row) > currency_idx and row[currency_idx]:
                currency = str(row[currency_idx])

        trend = [
            {"date": value["date"], "amount": round(float(value["amount"]), 2)}
            for _, value in sorted(daily.items(), key=lambda item: item[0])
        ]
        services = {
            name: round(amount, 2)
            for name, amount in sorted(by_service.items(), key=lambda item: item[1], reverse=True)
            if amount
        }
        mtd_spend = round(sum(item["amount"] for item in trend), 2)
        budget = settings.COST_BUDGET_MONTHLY_USD
        data_source = "live" if rows else "empty"

        payload = {
            "mtd_spend": mtd_spend,
            "last_month_spend": None,
            "budget_monthly": budget,
            "budget_utilisation_pct": round((mtd_spend / budget) * 100, 1) if budget else 0.0,
            "trend": trend,
            "by_service": services,
            "currency": currency,
            "data_source": data_source,
            "note": None if rows else "Cost data appears 24-48 h after first resource deployment.",
            "error": None,
        }
        logger.info("Cost summary OK: rows=%s MTD=%s%.2f source=%s", len(rows), currency, mtd_spend, data_source)
        return _store_summary(account, payload)

    except HttpResponseError as exc:
        stale = _cached_summary(account, allow_stale=True)
        if stale and stale.get("data_source") not in {"throttled", "error", "empty"}:
            if stale.get("data_source") == "consumption_usage_details":
                stale["note"] = "Showing cached live Azure Consumption usageDetails."
            else:
                stale["note"] = "Showing cached live Azure Cost Management data."
            stale["data_source"] = "cached"
            stale["error"] = None
            return stale

        if _is_billing_not_ready(exc):
            return _store_summary(account, _fallback(
                "Billing data is not available yet. This is normal for new/free-trial subscriptions.",
                data_source="empty",
            ))
        if _is_throttled(exc):
            try:
                usage_summary = await _usage_details_summary(account, first, now)
                if usage_summary is not None:
                    return _store_summary(account, usage_summary)
            except Exception as fallback_exc:
                logger.warning("Consumption usageDetails fallback failed: %s", fallback_exc)

            return _store_summary(account, _fallback(
                "Azure Cost Management is throttling requests. Wait a few minutes and refresh.",
                error="429 Too many requests",
                data_source="throttled",
            ))

        logger.error("AzureCostService HTTP error: %s", exc)
        code = getattr(getattr(exc, "error", None), "code", None)
        return _store_summary(
            account,
            _fallback("Cost Management API returned an error.", error=f"HttpResponseError: {code or exc}", data_source="error"),
        )

    except Exception as exc:
        logger.error("AzureCostService.get_mtd_summary failed: %s: %r", type(exc).__name__, exc)
        return _fallback("Unexpected error fetching cost data.", error=f"{type(exc).__name__}: {exc}", data_source="error")


async def get_cost_by_service(days: int = 30, account: AzureAccount | None = None) -> dict[str, Any]:
    """Return service costs from the same cached live summary to avoid extra API reads."""
    summary = await get_mtd_summary(account)
    by_service = summary.get("by_service") or {}
    total = sum(float(amount) for amount in by_service.values()) or 1.0
    services = [
        {
            "name": name,
            "amount": round(float(amount), 2),
            "pct": round((float(amount) / total) * 100, 1),
        }
        for name, amount in by_service.items()
    ]
    return {
        "period_days": days,
        "services": services,
        "currency": summary.get("currency", "USD"),
        "data_source": summary.get("data_source", "empty"),
        "note": summary.get("note"),
        "cached": summary.get("cached", False),
    }


async def get_cost_analysis(
    days: int = 30,
    account: AzureAccount | None = None,
    service: str = "",
    resource_group: str = "",
    region: str = "",
    resource_type: str = "",
    resource_ids: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
) -> dict[str, Any]:
    """
    Detailed live cost analysis by resource and meter/component.

    Uses Azure Consumption usageDetails because it exposes resourceId, meter
    category, product, region, and resource group in one feed and avoids extra
    Cost Management Query grouping calls.
    """
    account = account or current_account()
    if not account.configured:
        return {"items": [], "by_resource": [], "by_component": [], "data_source": "empty", "note": "Azure account is not connected."}

    now = datetime.now(timezone.utc)
    end = _parse_date_param(end_date) or now
    start = _parse_date_param(start_date) or (end - timedelta(days=max(1, min(int(days or 30), 365))))
    if start > end:
        start, end = end, start
    period_days = max(1, (end.date() - start.date()).days + 1)
    token = _credential(account).get_token("https://management.azure.com/.default").token
    url = (
        "https://management.azure.com"
        f"/subscriptions/{account.subscription_id}/providers/Microsoft.Consumption/usageDetails"
    )
    params: dict[str, str] | None = {
        "api-version": "2023-05-01",
        "$top": "1000",
        "$filter": (
            f"properties/usageStart ge '{start.date().isoformat()}' "
            f"and properties/usageEnd le '{end.date().isoformat()}'"
        ),
    }
    rows: list[dict[str, Any]] = []
    wanted_ids = {item.lower() for item in (resource_ids or []) if item}
    wanted_names = {_resource_name_from_id(item).lower() for item in (resource_ids or []) if item}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while url and len(rows) < 5000:
                response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                if response.status_code == 429:
                    return {
                        "items": [],
                        "by_resource": [],
                        "by_component": [],
                        "data_source": "throttled",
                        "note": "Azure Consumption usageDetails is throttling detailed cost analysis. Try a smaller filter or wait briefly.",
                    }
                response.raise_for_status()
                data = response.json()
                values = data.get("value") or []
                for item in values:
                    props = item.get("properties") or item
                    if not isinstance(props, dict):
                        continue
                    amount = _float_value(
                        props.get("costInBillingCurrency")
                        or props.get("pretaxCost")
                        or props.get("cost")
                        or props.get("extendedCost")
                    )
                    if amount == 0:
                        continue
                    instance_name = str(props.get("instanceName") or "")
                    resource_id = str(props.get("resourceId") or props.get("instanceId") or "")
                    if not resource_id and _looks_like_arm_id(instance_name):
                        resource_id = instance_name
                    service_name = str(props.get("consumedService") or props.get("meterCategory") or props.get("serviceName") or "Other")
                    group_name = str(props.get("resourceGroup") or props.get("resourceGroupName") or "")
                    location = str(props.get("resourceLocation") or props.get("location") or "")
                    component = str(props.get("meterSubCategory") or props.get("meterName") or props.get("product") or service_name)
                    item_type = _resource_type_from_id(resource_id)

                    if service and service.lower() not in service_name.lower():
                        continue
                    if resource_group and resource_group.lower() != group_name.lower():
                        continue
                    if region and _normalise_filter(region) not in _normalise_filter(location):
                        continue
                    if resource_type and not _resource_type_matches(resource_type, item_type, service_name, component):
                        continue
                    resource_name = _resource_name_from_id(resource_id) or _resource_name_from_id(instance_name) or instance_name
                    if wanted_ids and resource_id.lower() not in wanted_ids and resource_name.lower() not in wanted_names:
                        continue

                    rows.append({
                        "resource_id": resource_id,
                        "resource_name": resource_name,
                        "resource_type": item_type or "unknown",
                        "resource_group": group_name,
                        "region": location,
                        "service": service_name,
                        "component": component,
                        "amount": round(amount, 4),
                        "currency": str(props.get("billingCurrency") or props.get("currency") or props.get("currencyCode") or "INR"),
                    })
                url = data.get("nextLink")
                params = None

        by_resource = _rollup(rows, ("resource_id", "resource_name", "resource_type", "resource_group", "region"))
        by_component = _rollup(rows, ("service", "component"))
        return {
            "period_days": period_days,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "total": round(sum(item["amount"] for item in rows), 2),
            "currency": rows[0]["currency"] if rows else "INR",
            "items": rows[:500],
            "by_resource": by_resource[:50],
            "by_component": by_component[:50],
            "filters": {
                "service": service,
                "resource_group": resource_group,
                "region": region,
                "resource_type": resource_type,
                "resource_ids": list(wanted_ids),
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
            },
            "data_source": "live_usage_details",
            "note": None if rows else "No detailed cost rows matched the selected filters.",
        }
    except Exception as exc:
        logger.error("get_cost_analysis failed: %s: %s", type(exc).__name__, exc)
        return {
            "items": [],
            "by_resource": [],
            "by_component": [],
            "data_source": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _resource_type_from_id(resource_id: str) -> str:
    parts = [part for part in resource_id.split("/") if part]
    if "providers" not in [part.lower() for part in parts]:
        return ""
    lowered = [part.lower() for part in parts]
    idx = lowered.index("providers")
    if len(parts) > idx + 2:
        return f"{parts[idx + 1]}/{parts[idx + 2]}".lower()
    return ""


def _resource_name_from_id(resource_id: str) -> str:
    parts = [part for part in resource_id.split("/") if part]
    return parts[-1] if parts else ""


def _looks_like_arm_id(value: str) -> bool:
    return str(value or "").lower().startswith("/subscriptions/") and "/providers/" in str(value or "").lower()


def _rollup(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field, "") for field in fields)
        bucket = buckets.setdefault(key, {field: row.get(field, "") for field in fields} | {"amount": 0.0})
        bucket["amount"] += float(row.get("amount") or 0)
    return [
        {**bucket, "amount": round(bucket["amount"], 2)}
        for bucket in sorted(buckets.values(), key=lambda item: item["amount"], reverse=True)
    ]


def _normalise_filter(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _resource_type_matches(requested: str, item_type: str, service_name: str = "", component: str = "") -> bool:
    """Match ARM resource types and the friendly labels used by the UI."""
    requested_norm = _normalise_filter(requested)
    haystack = _normalise_filter(f"{item_type} {service_name} {component}")
    if not requested_norm:
        return True
    if requested_norm in haystack:
        return True

    aliases = {
        "appservice": ("microsoftwebsites", "microsoftwebserverfarms", "appservice", "webapp"),
        "webapp": ("microsoftwebsites", "appservice", "webapp"),
        "containerapp": ("microsoftappcontainerapps", "containerapp"),
        "virtualmachine": ("microsoftcomputevirtualmachines", "virtualmachine", "vm"),
        "vm": ("microsoftcomputevirtualmachines", "virtualmachine"),
        "storage": ("microsoftstorage", "storageaccount", "blob"),
        "storageaccount": ("microsoftstoragestorageaccounts", "storageaccount", "blob"),
        "database": ("microsoftdbformysql", "microsoftsql", "database"),
        "mysql": ("microsoftdbformysql", "mysql"),
        "sql": ("microsoftsql", "sql"),
        "virtualnetwork": ("microsoftnetworkvirtualnetworks", "virtualnetwork", "vnet"),
    }
    for alias, candidates in aliases.items():
        if requested_norm == alias or requested_norm in candidates:
            return any(candidate in haystack for candidate in candidates)
    return False


def _parse_date_param(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
