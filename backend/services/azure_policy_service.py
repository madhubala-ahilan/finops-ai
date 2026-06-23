from __future__ import annotations

from typing import Any, Dict


async def get_policy_compliance_summary() -> Dict[str, Any]:
    from services.azure_account import current_account

    try:
        from azure.mgmt.policyinsights import PolicyInsightsClient
        from azure.mgmt.policyinsights.models import QueryOptions

        account = current_account()
        
        # ✅ Pass both credential AND subscription_id
        client = PolicyInsightsClient(
            credential=account.credential(),
            subscription_id=account.subscription_id,
        )
        
        scope = f"/subscriptions/{account.subscription_id}"
        query_options = QueryOptions(
            top=100,
            filter="ComplianceState ne 'Compliant'",
            select="PolicyAssignmentName,PolicyDefinitionName,ComplianceState,ResourceId,Timestamp",
        )
        states = list(client.policy_states.list_query_results_for_subscription(
            policy_states_resource="latest",
            subscription_id=account.subscription_id,
            query_options=query_options,
        ))
        rows = []
        by_state: dict[str, int] = {}
        for state in states:
            compliance_state = getattr(state, "compliance_state", "Unknown") or "Unknown"
            by_state[compliance_state] = by_state.get(compliance_state, 0) + 1
            rows.append({
                "assignment": getattr(state, "policy_assignment_name", None),
                "definition": getattr(state, "policy_definition_name", None),
                "compliance_state": compliance_state,
                "resource_id": getattr(state, "resource_id", None),
                "timestamp": str(getattr(state, "timestamp", "")),
            })
        return {
            "data_source": "live",
            "scope": scope,
            "total_non_compliant": len(rows),
            "by_state": by_state,
            "items": rows,
            "note": None if rows else "No non-compliant resources found.",
        }
    except ImportError:
        return {
            "data_source": "not_configured",
            "total_non_compliant": 0,
            "by_state": {},
            "items": [],
            "note": "Install azure-mgmt-policyinsights to enable live Azure Policy compliance queries.",
        }
    except Exception as exc:
        error_msg = str(exc)
        # Detect the real cause
        if "AuthorizationFailed" in error_msg:
            note = "RBAC permission denied — check Policy Insights role."
        elif "not registered" in error_msg.lower() or "MissingSubscriptionRegistration" in error_msg:
            note = "Resource provider Microsoft.PolicyInsights is not registered. Run: az provider register --namespace Microsoft.PolicyInsights"
        elif "not found" in error_msg.lower() or "404" in error_msg:
            note = "Policy Insights endpoint not found — provider may not be registered."
        else:
            note = f"Unexpected error: {error_msg}"
    
        return {
            "data_source": "error",
            "total_non_compliant": 0,
            "by_state": {},
            "items": [],
            "error": error_msg,   # ← log the REAL error
            "note": note,
        }