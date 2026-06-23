from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger("finops.ml.anomaly")


def _build_matrix(records: List[Dict[str, float]]) -> np.ndarray:
    rows = []
    for record in records:
        rows.append([
            record.get("daily_spend", 0.0),
            record.get("network_cost", 0.0),
            record.get("compute_cost", 0.0),
            record.get("storage_cost", 0.0),
            record.get("sudden_delta", 0.0),
        ])
    return np.array(rows, dtype=float)


def run_detection(
    metrics: List[Dict[str, Any]] | None = None,
    contamination: float = 0.10,
) -> Dict[str, Any]:
    if not metrics:
        return {"total": 0, "critical": 0, "warning": 0, "info": 0, "items": [], "data_source": "empty"}

    if len(metrics) < 5:
        return {"total": 0, "critical": 0, "warning": 0, "info": 0, "items": [], "data_source": "empty"}

    matrix = _build_matrix(metrics)
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0)
    stds[stds == 0] = 1.0
    normalized = (matrix - means) / stds

    try:
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            max_samples="auto",
            random_state=42,
        )
        model.fit(normalized)
        scores = model.score_samples(normalized)
        labels = model.predict(normalized)
    except Exception as exc:
        logger.warning("IsolationForest failed (%s); using z-score fallback", exc)
        scores = -np.max(np.abs(normalized), axis=1)
        labels = np.where(scores < -1.5, -1, 1)

    anomalies = []
    for index, (metric, score, label) in enumerate(zip(metrics, scores, labels)):
        if label != -1:
            continue
        anomalies.append({
            "id": f"anm-{index:03d}",
            "severity": _score_to_severity(float(score)),
            "title": "Unusual live spend pattern",
            "resource": metric.get("resource", "subscription-aggregate"),
            "date": metric.get("date", ""),
            "daily_spend": metric.get("daily_spend", 0.0),
            "delta": f"{metric.get('sudden_delta', 0.0):+.0f} USD/day",
            "iso_score": round(float(score), 4),
            "status": "open",
            "detected_at": metric.get("date", ""),
            "description": "Anomaly detected from live Azure metric/cost records.",
            "recommended_action": "Review the matching Azure Cost Management and Resource Graph records.",
        })

    return {
        "total": len(anomalies),
        "critical": sum(1 for item in anomalies if item["severity"] == "critical"),
        "warning": sum(1 for item in anomalies if item["severity"] == "warning"),
        "info": sum(1 for item in anomalies if item["severity"] == "info"),
        "items": anomalies,
        "data_source": "ml_model",
    }


def _score_to_severity(score: float) -> str:
    if score < -0.60:
        return "critical"
    if score < -0.40:
        return "warning"
    return "info"
