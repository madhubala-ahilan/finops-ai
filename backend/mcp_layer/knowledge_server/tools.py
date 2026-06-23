"""
mcp/knowledge_server/tools.py — Knowledge MCP Server (RAG)

Tools:
  search_azure_docs()           → Azure docs semantic search
  retrieve_finops_rules()       → FinOps best practices
  retrieve_troubleshooting_playbook() → Incident playbooks
  get_pricing_info()            → Azure service pricing

Used by: RAG agent (Phase 6, requires Azure AI Search)
"""

from mcp_layer.tool_registry import tool_registry

# ── Local knowledge base (used until Azure AI Search is configured) ────────────

_FINOPS_RULES = [
    {"rule": "Right-size VMs with CPU < 20% over 7 days", "category": "cost", "impact": "High"},
    {"rule": "Delete storage accounts idle > 90 days", "category": "cost", "impact": "Medium"},
    {"rule": "Use Reserved Instances for production VMs (1-3yr)", "category": "cost", "impact": "High"},
    {"rule": "Enable auto-shutdown for dev/test VMs (6PM-8AM)", "category": "cost", "impact": "Medium"},
    {"rule": "Move infrequently accessed blobs to Cool tier", "category": "cost", "impact": "Low"},
    {"rule": "Tag all resources with cost-centre and owner", "category": "governance", "impact": "Medium"},
    {"rule": "Set budget alerts at 80% and 90% utilisation", "category": "governance", "impact": "High"},
    {"rule": "Enable Azure Defender for critical resources", "category": "security", "impact": "High"},
]

_PLAYBOOKS = {
    "high_cpu_vm": [
        "1. Check process list via Azure Serial Console",
        "2. Review App Insights for runaway jobs",
        "3. Scale up VM SKU if legitimate load",
        "4. If idle process: stop_vm → schedule off-peak restart",
    ],
    "missing_blob_asset": [
        "1. Confirm asset is missing: check_blob_asset()",
        "2. Check blob versioning history",
        "3. Restore from backup container: restore_blob()",
        "4. Invalidate CDN cache after restore",
        "5. Alert web team: send_teams_alert()",
    ],
    "budget_breach": [
        "1. Run detect_cost_anomalies() to find spike source",
        "2. Get advisor recommendations: get_advisor_recommendations()",
        "3. Identify top 3 spenders: get_cost_by_service()",
        "4. Propose downsizing: queue in Approval Queue",
        "5. Alert finance team: send_teams_alert(severity='critical')",
    ],
    "app_service_down": [
        "1. Check health: get_resource_health()",
        "2. Review App Insights errors: get_app_insights_errors()",
        "3. Restart app service: restart_app_service()",
        "4. If recurring: check deployment logs",
        "5. Escalate if not resolved in 5 min",
    ],
}


@tool_registry.register(
    name="retrieve_finops_rules",
    server="knowledge",
    description="FinOps best-practice rules for cost optimisation and governance",
    tags=["finops", "rules", "knowledge", "rag"],
)
async def retrieve_finops_rules(
    category: str = "",
    impact: str = "",
    **kwargs,
) -> dict:
    rules = _FINOPS_RULES
    if category:
        rules = [r for r in rules if r["category"] == category.lower()]
    if impact:
        rules = [r for r in rules if r["impact"] == impact.capitalize()]
    return {
        "rules":       rules,
        "total":       len(rules),
        "data_source": "local_kb",
        "note":        "Phase 6: Upgrade to Azure AI Search for semantic retrieval",
    }


@tool_registry.register(
    name="retrieve_troubleshooting_playbook",
    server="knowledge",
    description="Step-by-step incident response playbook for known failure patterns",
    tags=["playbook", "incident", "knowledge", "rag"],
)
async def retrieve_troubleshooting_playbook(
    incident_type: str = "",
    **kwargs,
) -> dict:
    playbook = _PLAYBOOKS.get(incident_type, [])
    if not playbook:
        # Return closest match
        available = list(_PLAYBOOKS.keys())
        return {
            "incident_type": incident_type,
            "steps":         [],
            "available":     available,
            "note":          f"No playbook for '{incident_type}'. Available: {available}",
            "data_source":   "local_kb",
        }
    return {
        "incident_type": incident_type,
        "steps":         playbook,
        "data_source":   "local_kb",
        "note":          "Phase 6: Upgrade to Azure AI Search for vector similarity search",
    }


@tool_registry.register(
    name="search_azure_docs",
    server="knowledge",
    description="Semantic search over Azure documentation and pricing pages",
    tags=["docs", "search", "rag", "azure"],
)
async def search_azure_docs(query: str = "", **kwargs) -> dict:
    """Search Azure AI Search when configured; otherwise use the local KB."""
    try:
        from config import settings
        endpoint = getattr(settings, "AZURE_SEARCH_ENDPOINT", "")
        index_name = getattr(settings, "AZURE_SEARCH_INDEX", "")
        api_key = getattr(settings, "AZURE_SEARCH_KEY", "")
        if endpoint and index_name and api_key:
            from azure.core.credentials import AzureKeyCredential
            from azure.search.documents.aio import SearchClient

            client = SearchClient(endpoint, index_name, AzureKeyCredential(api_key))
            docs = []
            results = await client.search(query, top=5)
            async for item in results:
                docs.append(dict(item))
            await client.close()
            return {
                "query": query,
                "results": docs,
                "total": len(docs),
                "data_source": "azure_ai_search",
            }
    except Exception as exc:
        return {"query": query, "results": [], "total": 0, "data_source": "error", "error": str(exc)}

    query_lower = query.lower()
    results = []

    if any(w in query_lower for w in ["cost", "billing", "spend", "budget"]):
        results.append({
            "title":   "Azure Cost Management + Billing documentation",
            "url":     "https://docs.microsoft.com/en-us/azure/cost-management-billing/",
            "snippet": "Understand and manage your Azure costs. Set budgets, alerts, and optimize spending.",
        })

    if any(w in query_lower for w in ["vm", "virtual machine", "compute"]):
        results.append({
            "title":   "Virtual Machine pricing",
            "url":     "https://azure.microsoft.com/en-us/pricing/details/virtual-machines/",
            "snippet": "Azure VM pricing for all series: B, D, E, F, M, NC, ND series.",
        })

    if any(w in query_lower for w in ["storage", "blob"]):
        results.append({
            "title":   "Azure Blob Storage pricing",
            "url":     "https://azure.microsoft.com/en-us/pricing/details/storage/blobs/",
            "snippet": "Hot, Cool, Cold, Archive tiers. LRS, GRS, ZRS redundancy options.",
        })

    if not results:
        results.append({
            "title":   "Azure documentation",
            "url":     "https://docs.microsoft.com/en-us/azure/",
            "snippet": "Search Azure docs for " + query,
        })

    return {
        "query":       query,
        "results":     results,
        "total":       len(results),
        "data_source": "local_kb",
        "note":        "Phase 6: Replace with Azure AI Search semantic vector search",
    }


@tool_registry.register(
    name="get_pricing_info",
    server="knowledge",
    description="Azure service pricing for cost estimation and rightsizing recommendations",
    tags=["pricing", "cost", "knowledge"],
)
async def get_pricing_info(service: str = "", sku: str = "", region: str = "eastus", **kwargs) -> dict:
    # Static pricing data for common services — Phase 6: Azure Retail Prices API
    prices = {
        "vm": {
            "Standard_B1s":  0.0104, "Standard_B2s": 0.0416,
            "Standard_D2s_v3": 0.096, "Standard_D4s_v3": 0.192,
            "Standard_D8s_v3": 0.384,
        },
        "storage": {"LRS_hot": 0.018, "LRS_cool": 0.01, "GRS_hot": 0.036},
        "sql":     {"Basic": 4.99, "Standard_S1": 14.99, "Standard_S3": 149.99},
    }
    svc_prices = prices.get(service.lower(), {})
    if sku:
        price = svc_prices.get(sku)
        return {
            "service": service, "sku": sku, "region": region,
            "price_per_hour": price,
            "price_per_month": round(price * 730, 2) if price else None,
            "data_source": "static",
        }
    return {
        "service": service, "region": region,
        "available_skus": svc_prices,
        "data_source": "static",
        "note": "Phase 6: Use Azure Retail Prices API for real-time pricing",
    }
