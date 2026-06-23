"""
ml/isolation_forest.py — Isolation Forest anomaly detection on Azure cost data.

Architecture:
  Phase 2A: Uses daily cost trend from Azure Cost Management as input.
  Phase 3:  Will also accept Azure Monitor metrics (CPU, memory, egress).

Algorithm:
  sklearn IsolationForest trains on historical daily costs.
  Points with score < threshold are flagged as anomalies.
  Severity is determined by how far below threshold the score falls.

Usage:
  from ml.isolation_forest import detect_cost_anomalies

  daily_costs = [120.5, 118.2, 125.0, 310.0, 122.3]  # from cost trend
  anomalies = detect_cost_anomalies(daily_costs, trend_objects)
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger("finops.ml.isolation_forest")

# ── Config ────────────────────────────────────────────────────────────────────
CONTAMINATION    = 0.1     # expected fraction of anomalous points
CRITICAL_THRESH  = -0.55   # isolation score below this → critical
WARNING_THRESH   = -0.30   # isolation score below this → warning
MIN_SAMPLES      = 5       # need at least this many data points


def detect_cost_anomalies(
    daily_costs: List[float],
    trend_objects: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Run Isolation Forest on a list of daily Azure spend values.

    Args:
        daily_costs:   List of daily cost floats e.g. [120.5, 118.0, 315.2, ...]
        trend_objects: Optional list of {date, amount} dicts from cost API trend.
                       Used to label anomalies with real dates.

    Returns:
        List of anomaly dicts compatible with the frontend AnomalyFeed format.
        Empty list if not enough data or no anomalies found.
    """
    if len(daily_costs) < MIN_SAMPLES:
        logger.info(f"Not enough data for Isolation Forest ({len(daily_costs)} < {MIN_SAMPLES})")
        return []

    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest

        # ── Feature engineering ───────────────────────────────────────────────
        costs_arr = np.array(daily_costs).reshape(-1, 1)

        # Add rolling features to improve detection quality
        rolling_3 = np.convolve(daily_costs, np.ones(3)/3, mode='same')
        pct_change = np.array([0.0] + [
            (daily_costs[i] - daily_costs[i-1]) / max(daily_costs[i-1], 1)
            for i in range(1, len(daily_costs))
        ])

        X = np.column_stack([costs_arr, rolling_3.reshape(-1,1), pct_change])

        # ── Train + score ─────────────────────────────────────────────────────
        model = IsolationForest(
            contamination=CONTAMINATION,
            random_state=42,
            n_estimators=100,
        )
        model.fit(X)
        scores   = model.score_samples(X)   # lower = more anomalous
        baseline = float(np.mean(daily_costs))
        std_dev  = float(np.std(daily_costs))

        # ── Build anomaly objects ─────────────────────────────────────────────
        anomalies = []
        for i, (cost, score) in enumerate(zip(daily_costs, scores)):
            if score >= WARNING_THRESH:
                continue  # normal point

            severity = "critical" if score < CRITICAL_THRESH else "warning"
            delta_pct = ((cost - baseline) / max(baseline, 1)) * 100
            delta_str = f"+{delta_pct:.0f}%" if delta_pct > 0 else f"{delta_pct:.0f}%"
            delta_dollar = cost - baseline
            dollar_str = f"+${delta_dollar:.0f}/day" if delta_dollar > 0 else f"${delta_dollar:.0f}/day"

            # Get date label from trend objects if available
            date_label = "unknown"
            if trend_objects and i < len(trend_objects):
                date_label = trend_objects[i].get("date", str(i))

            anomalies.append({
                "id":           f"ML-{i+1:03d}",
                "title":        _make_title(cost, baseline, severity),
                "resource":     "subscription/azure-cost",
                "res":          "subscription/azure-cost",
                "severity":     severity,
                "sev":          severity,
                "time":         f"Day {date_label}",
                "delta":        f"{delta_str} ({dollar_str})",
                "status":       "open",
                "description":  (
                    f"Daily spend ${cost:.2f} vs baseline ${baseline:.2f}. "
                    f"Isolation score: {score:.3f}. "
                    f"Std dev: ${std_dev:.2f}"
                ),
                "recommended_action": _recommend(cost, baseline, severity),
                "ml_score":     round(float(score), 4),
                "detected_at":  datetime.now(timezone.utc).isoformat(),
            })

        logger.info(
            f"Isolation Forest: {len(daily_costs)} days → "
            f"{len(anomalies)} anomalies detected"
        )
        return anomalies

    except ImportError:
        logger.warning(
            "scikit-learn not installed. "
            "Run: pip install scikit-learn --break-system-packages"
        )
        return []
    except Exception as exc:
        logger.error(f"Isolation Forest failed: {type(exc).__name__}: {exc}")
        return []


def detect_resource_anomalies(
    metric_series: List[Dict],
    resource_name: str,
    metric_name: str,
) -> Optional[Dict]:
    """
    Detect anomaly in a single resource metric time series.

    Args:
        metric_series: List of {timestamp, value} dicts from Azure Monitor.
        resource_name: Azure resource name.
        metric_name:   e.g. "CPU percentage", "DTU consumption".

    Returns:
        Anomaly dict if anomalous, None if normal.

    Phase 3: This method will be wired to AzureMonitorService.get_metrics().
    """
    if not metric_series or len(metric_series) < MIN_SAMPLES:
        return None

    values = [m.get("value", 0) for m in metric_series]
    anomalies = detect_cost_anomalies(values)
    if not anomalies:
        return None

    worst = min(anomalies, key=lambda a: a.get("ml_score", 0))
    worst["resource"] = resource_name
    worst["res"] = resource_name
    worst["title"] = f"Anomalous {metric_name} on {resource_name}"
    return worst


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_title(cost: float, baseline: float, severity: str) -> str:
    if cost > baseline * 1.5:
        return f"Large cost spike — ${cost:.0f} vs ${baseline:.0f} baseline"
    if cost > baseline * 1.2:
        return f"Cost spike detected — ${cost:.0f} vs ${baseline:.0f} average"
    if cost < baseline * 0.3:
        return f"Unusually low spend — possible resource outage"
    return f"Anomalous spend pattern — Isolation Forest flagged"


def _recommend(cost: float, baseline: float, severity: str) -> str:
    if severity == "critical":
        if cost > baseline:
            return "Investigate for runaway processes, misconfigured autoscaling, or data ingestion spike"
        return "Verify no critical services went offline unexpectedly"
    return "Monitor for 24h; check for new resource deployments or pricing changes"
