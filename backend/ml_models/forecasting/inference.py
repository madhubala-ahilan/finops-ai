from __future__ import annotations

from typing import Any, Dict, List


def run_forecast(horizon_days: int, history: List[float] | None = None) -> Dict[str, Any]:
    if not history or len(history) < 5:
        return {
            "horizon_days": horizon_days,
            "predictions": [],
            "data_source": "empty",
            "note": "Provide at least 5 live daily cost points to run forecasting.",
        }

    from ml.xgboost_forecast import forecast_spend

    return forecast_spend(history, horizon=horizon_days)
