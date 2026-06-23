"""
ml/xgboost_forecast.py — XGBoost cloud spend forecasting.

Architecture:
  Phase 2B: Trains on daily cost history from Azure Cost Management.
  Phase 4:  ForecastingAgent wraps this with LLM narrative explanation.

Features engineered per day:
  • day_of_week  (0=Mon … 6=Sun)
  • day_of_month
  • month_number
  • rolling_7d_avg
  • rolling_30d_avg
  • rolling_7d_std
  • pct_change_1d
  • pct_change_7d

Fallback: linear regression when history < 14 days.
          simple average when history < 5 days.

Usage:
  from ml.xgboost_forecast import forecast_spend

  result = forecast_spend(daily_costs, horizon=14)
  # result = {
  #   "method": "xgboost",
  #   "horizon_days": 14,
  #   "predictions": [320.5, 315.2, ...],  # one per day
  #   "confidence_lo": [...],
  #   "confidence_hi": [...],
  #   "series": [{date, actual, predicted, lo, hi}, ...],
  #   "mae": 12.3,
  #   "rmse": 18.4,
  # }
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("finops.ml.xgboost")

# ── Config ────────────────────────────────────────────────────────────────────
MIN_XGBOOST_SAMPLES   = 14    # need ≥14 days for XGBoost
MIN_LINEAR_SAMPLES    = 5     # need ≥5 days for linear fallback
CONFIDENCE_WIDTH      = 0.12  # ±12% confidence band


def forecast_spend(
    daily_costs: List[float],
    horizon: int = 14,
    trend_objects: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Forecast future Azure daily spend.

    Args:
        daily_costs:   Historical daily cost values (oldest → newest).
        horizon:       Number of future days to forecast.
        trend_objects: Optional [{date, amount}] from cost API for date labels.

    Returns:
        Forecast dict with predictions, confidence bands, and series for charts.
    """
    n = len(daily_costs)

    if n < MIN_LINEAR_SAMPLES:
        return _simple_average_forecast(daily_costs, horizon, trend_objects)

    if n < MIN_XGBOOST_SAMPLES:
        return _linear_forecast(daily_costs, horizon, trend_objects)

    return _xgboost_forecast(daily_costs, horizon, trend_objects)


# ── XGBoost ───────────────────────────────────────────────────────────────────

def _xgboost_forecast(
    daily_costs: List[float],
    horizon: int,
    trend_objects: Optional[List[Dict]],
) -> Dict[str, Any]:
    try:
        import numpy as np
        import xgboost as xgb

        costs = np.array(daily_costs, dtype=float)
        X, y = _build_features(costs)

        if len(X) < 3:
            return _linear_forecast(daily_costs, horizon, trend_objects)

        # Train / validation split
        split = max(1, int(len(X) * 0.8))
        X_train, y_train = X[:split], y[:split]
        X_val,   y_val   = X[split:], y[split:]

        model = xgb.XGBRegressor(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)] if len(X_val) > 0 else None,
            verbose=False,
        )

        # Compute validation error
        if len(X_val) > 0:
            preds_val = model.predict(X_val)
            mae  = float(np.mean(np.abs(preds_val - y_val)))
            rmse = float(np.sqrt(np.mean((preds_val - y_val)**2)))
        else:
            mae  = float(np.mean(np.abs(model.predict(X_train) - y_train)))
            rmse = mae * 1.2

        # ── Recursive multi-step forecasting ──────────────────────────────────
        working_costs = list(costs)
        predictions   = []
        for step in range(horizon):
            step_arr = np.array(working_costs, dtype=float)
            feat_row = _build_single_feature(step_arr, step)
            pred = float(max(0, model.predict(feat_row.reshape(1, -1))[0]))
            predictions.append(round(pred, 2))
            working_costs.append(pred)

        series = _build_series(daily_costs, predictions, trend_objects, horizon)

        logger.info(
            f"XGBoost forecast: {len(daily_costs)}d history → "
            f"{horizon}d horizon | MAE={mae:.1f} RMSE={rmse:.1f}"
        )

        return {
            "method":         "xgboost",
            "horizon_days":   horizon,
            "predictions":    predictions,
            "confidence_lo":  [round(p * (1 - CONFIDENCE_WIDTH), 2) for p in predictions],
            "confidence_hi":  [round(p * (1 + CONFIDENCE_WIDTH), 2) for p in predictions],
            "series":         series,
            "mae":            round(mae, 2),
            "rmse":           round(rmse, 2),
            "training_days":  len(daily_costs),
            "model_version":  f"xgb-n{len(daily_costs)}",
        }

    except ImportError:
        logger.warning(
            "xgboost not installed — falling back to linear regression. "
            "Run: pip install xgboost --break-system-packages"
        )
        return _linear_forecast(daily_costs, horizon, trend_objects)
    except Exception as exc:
        logger.error(f"XGBoost failed: {type(exc).__name__}: {exc} — linear fallback")
        return _linear_forecast(daily_costs, horizon, trend_objects)


# ── Feature engineering ───────────────────────────────────────────────────────

def _build_features(costs):
    """Build (X, y) arrays from a cost series using lagged/rolling features."""
    import numpy as np

    window = 7
    n = len(costs)
    rows, targets = [], []

    for i in range(window, n - 1):
        row = _build_single_feature(costs[:i+1], 0)
        rows.append(row)
        targets.append(costs[i + 1])

    if not rows:
        return np.empty((0, 8)), np.empty(0)

    return np.array(rows), np.array(targets)


def _build_single_feature(costs, future_offset: int):
    """Build a single feature vector for one prediction step."""
    import numpy as np

    costs = np.array(costs, dtype=float)
    n = len(costs)

    # Date features (relative to today + offset)
    ref_date = datetime.now() + timedelta(days=future_offset)
    day_of_week   = ref_date.weekday()   # 0=Mon … 6=Sun
    day_of_month  = ref_date.day
    month_number  = ref_date.month

    last        = costs[-1]
    rolling_7   = float(np.mean(costs[-7:]))  if n >= 7  else float(np.mean(costs))
    rolling_30  = float(np.mean(costs[-30:])) if n >= 30 else float(np.mean(costs))
    rolling_std = float(np.std(costs[-7:]))   if n >= 7  else float(np.std(costs))
    pct_1d = (costs[-1] - costs[-2]) / max(costs[-2], 1) if n >= 2 else 0.0
    pct_7d = (costs[-1] - costs[-7]) / max(costs[-7], 1) if n >= 7 else 0.0

    return np.array([
        day_of_week, day_of_month, month_number,
        rolling_7, rolling_30, rolling_std,
        pct_1d, pct_7d,
    ], dtype=float)


# ── Fallback methods ──────────────────────────────────────────────────────────

def _linear_forecast(
    daily_costs: List[float],
    horizon: int,
    trend_objects: Optional[List[Dict]],
) -> Dict[str, Any]:
    """Linear regression fallback for 5-13 days of history."""
    try:
        import numpy as np
        from sklearn.linear_model import LinearRegression

        costs = np.array(daily_costs, dtype=float)
        X = np.arange(len(costs)).reshape(-1, 1)
        model = LinearRegression().fit(X, costs)

        future_X = np.arange(len(costs), len(costs) + horizon).reshape(-1, 1)
        preds = [max(0, float(p)) for p in model.predict(future_X)]

        residuals = costs - model.predict(X)
        rmse = float(np.sqrt(np.mean(residuals**2)))
        mae  = float(np.mean(np.abs(residuals)))

        series = _build_series(daily_costs, preds, trend_objects, horizon)

        return {
            "method": "linear_regression",
            "horizon_days": horizon,
            "predictions": [round(p, 2) for p in preds],
            "confidence_lo": [round(p * (1 - CONFIDENCE_WIDTH), 2) for p in preds],
            "confidence_hi": [round(p * (1 + CONFIDENCE_WIDTH), 2) for p in preds],
            "series": series,
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "training_days": len(daily_costs),
            "model_version": "linear-fallback",
        }
    except ImportError:
        return _simple_average_forecast(daily_costs, horizon, trend_objects)


def _simple_average_forecast(
    daily_costs: List[float],
    horizon: int,
    trend_objects: Optional[List[Dict]],
) -> Dict[str, Any]:
    """Simplest fallback: repeat the recent average."""
    avg = sum(daily_costs[-3:]) / max(len(daily_costs[-3:]), 1) if daily_costs else 0
    preds = [round(avg, 2)] * horizon
    series = _build_series(daily_costs, preds, trend_objects, horizon)

    return {
        "method": "average_fallback",
        "horizon_days": horizon,
        "predictions": preds,
        "confidence_lo": [round(p * 0.88, 2) for p in preds],
        "confidence_hi": [round(p * 1.12, 2) for p in preds],
        "series": series,
        "mae": 0.0,
        "rmse": 0.0,
        "training_days": len(daily_costs),
        "model_version": "average-fallback",
    }


# ── Series builder for frontend chart ────────────────────────────────────────

def _build_series(
    actuals: List[float],
    predictions: List[float],
    trend_objects: Optional[List[Dict]],
    horizon: int,
) -> List[Dict]:
    """Build chart-ready series combining actual + forecast points."""
    series = []

    for i, cost in enumerate(actuals):
        date_label = trend_objects[i]["date"] if trend_objects and i < len(trend_objects) else f"D{i+1}"
        series.append({
            "date":      date_label,
            "actual":    round(cost, 2),
            "predicted": None,
            "lo":        None,
            "hi":        None,
        })

    for i, pred in enumerate(predictions):
        series.append({
            "date":      f"+{i+1}d",
            "actual":    None,
            "predicted": round(pred, 2),
            "lo":        round(pred * (1 - CONFIDENCE_WIDTH), 2),
            "hi":        round(pred * (1 + CONFIDENCE_WIDTH), 2),
        })

    return series
