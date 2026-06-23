"""
services/recommendation_service.py
Aggregates and ranks cost + reliability recommendations from:
  1. Azure Advisor (live API)
  2. ML anomaly agent findings
  3. Static FinOps best-practice rules

Architecture role: called by Optimization Agent and Advisor Agent.
"""

from __future__ import annotations
import logging
from typing import List, Dict, Any

from services.azure_resource_service import get_advisor_recommendations

logger = logging.getLogger("finops.recommendations")


# ── Impact scoring ────────────────────────────────────────────────────────────

_IMPACT_SCORE = {"High": 3, "Medium": 2, "Low": 1, "": 0}

def _score(rec: Dict[str, Any]) -> int:
    return _IMPACT_SCORE.get(str(rec.get("impact", "")), 0)


# ── Static FinOps rule library ────────────────────────────────────────────────

_STATIC_RULES: List[Dict[str, Any]] = [
    {
        "id":                "rule-001",
        "source":            "FinOps Rules",
        "category":          "Cost",
        "impact":            "High",
        "title":             "Enable Azure Hybrid Benefit on Windows VMs",
        "resource":          "subscription-wide",
        "short_description": "Apply Windows Server licences you already own to Azure VMs. Saves up to 40% on VM compute.",
        "problem":           "Paying on-demand Windows licensing when you may have SA coverage.",
        "potential_savings": "~40% on eligible VMs",
    },
    {
        "id":                "rule-002",
        "source":            "FinOps Rules",
        "category":          "Cost",
        "impact":            "Medium",
        "title":             "Enable blob lifecycle management on all storage accounts",
        "resource":          "subscription-wide",
        "short_description": "Automatically move cold blobs to Cool/Archive tier after 30/90 days.",
        "problem":           "Hot-tier blobs idle for 90+ days incur unnecessary cost.",
        "potential_savings":  "20–60% on blob storage",
    },
    {
        "id":                "rule-003",
        "source":            "FinOps Rules",
        "category":          "Reliability",
        "impact":            "Medium",
        "title":             "Enable soft delete on Key Vault",
        "resource":          "subscription-wide",
        "short_description": "Protect secrets from accidental deletion with 90-day recovery window.",
        "problem":           "Key Vault without soft delete is unrecoverable on accidental deletion.",
        "potential_savings":  "Prevents incident cost",
    },
    {
        "id":                "rule-004",
        "source":            "FinOps Rules",
        "category":          "Cost",
        "impact":            "High",
        "title":             "Tag all resources with CostCenter and Owner",
        "resource":          "subscription-wide",
        "short_description": "Untagged resources cannot be chargeback'd to teams, hiding waste.",
        "problem":           "Approximately 30% of resources have no cost-allocation tags.",
        "potential_savings":  "Enables chargeback governance",
    },
    {
        "id":                "rule-005",
        "source":            "FinOps Rules",
        "category":          "Cost",
        "impact":            "High",
        "title":             "Set budget alerts at 80% and 100% thresholds",
        "resource":          "subscription-wide",
        "short_description": "Azure Cost Management budget alerts prevent surprise overruns.",
        "problem":           "No automated budget alert configured on subscription.",
        "potential_savings":  "Prevents budget overruns",
    },
]


# ── Public API ────────────────────────────────────────────────────────────────

async def get_all_recommendations() -> Dict[str, Any]:
    """
    Fetches live Advisor recommendations, merges with static FinOps rules,
    deduplicates, and returns a ranked list.
    """
    # Live Azure Advisor
    try:
        advisor_recs = await get_advisor_recommendations()
        for r in advisor_recs:
            r["source"] = "Azure Advisor"
    except Exception as exc:
        logger.warning("Advisor fetch failed: %s", exc)
        advisor_recs = []

    # Merge with static rules
    all_recs = advisor_recs + _STATIC_RULES

    # Rank by impact score (High → Medium → Low)
    all_recs.sort(key=_score, reverse=True)

    # Counts
    total    = len(all_recs)
    by_cat: Dict[str, int] = {}
    by_imp: Dict[str, int] = {}
    for r in all_recs:
        cat = r.get("category", "Other")
        imp = r.get("impact",   "Low")
        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_imp[imp] = by_imp.get(imp, 0) + 1

    return {
        "total":              total,
        "by_category":        by_cat,
        "by_impact":          by_imp,
        "recommendations":    all_recs,
        "data_source":        "live+rules",
    }


async def get_cost_recommendations() -> List[Dict[str, Any]]:
    """Cost-only recommendations (used by FinOps Agent)."""
    result = await get_all_recommendations()
    return [r for r in result["recommendations"] if r.get("category") == "Cost"]


async def get_reliability_recommendations() -> List[Dict[str, Any]]:
    """Reliability / HA recommendations (used by CloudOps Agent)."""
    result = await get_all_recommendations()
    return [r for r in result["recommendations"] if r.get("category") in ("HighAvailability", "Reliability")]
