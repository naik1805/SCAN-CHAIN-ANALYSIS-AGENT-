"""SCD-FR-010 — Diagnosis confidence scoring.

Per-cell confidence is a calibrated composite (no artificial floor):

    evidence = 0.40 * relative_dominance
             + 0.25 * pattern_corroboration
             + 0.20 * obs_share
             + 0.15 * fail_type_consistency

    confidence = 0.50 * evidence + 0.50 * ml_pfa_probability   (sklearn GBM)
              or 0.55 * evidence + 0.45 * ml_pfa_probability   (legacy logistic)

Where:
  - relative_dominance: observations / max(observations on same chain)
  - pattern_corroboration: corroborating_patterns / max patterns on same chain
  - obs_share: observations / chain_observations
  - fail_type_consistency: share of this cell's obs matching its dominant fail type
  - ml_pfa_probability: calibrated Gradient Boosting P(PFA confirmed | features)
    trained on historical PFA records; at inference pattern_consistency = evidence_score

Dashboard / KPI aggregation (``aggregate_diagnosis_confidence``):
  fail-weighted mean of per-chain top-1 confidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

CONFIDENCE_DEFINITION = (
    "Per-cell: 0.50*evidence + 0.50*calibrated_GBM_confirmation_prob (or 0.55/0.45 logistic fallback); "
    "evidence = 0.40*relative_dominance + 0.25*pattern_corroboration "
    "+ 0.20*obs_share + 0.15*fail_type_consistency. "
    "ML: isotonic-calibrated Gradient Boosting on historical verified confirmations. "
    "Dashboard KPI: fail-weighted mean of per-chain top-1 confidence."
)

# Evidence sub-weights (must sum to 1.0)
_W_REL_DOM = 0.40
_W_PATTERN = 0.25
_W_OBS_SHARE = 0.20
_W_FAIL_TYPE = 0.15

# Blend when sklearn model is active vs legacy logistic JSON
_W_EVIDENCE_SKLEARN = 0.50
_W_ML_SKLEARN = 0.50
_W_EVIDENCE_LOGISTIC = 0.55
_W_ML_LOGISTIC = 0.45

FEATURE_COLS = [
    "pattern_consistency",
    "offset_ratio",
    "log_pattern_count",
    "relative_dominance",
    "pattern_corroboration",
    "obs_share",
    "fail_type_consistency",
    "rc_SHIFT",
    "rc_SETUP",
    "rc_HOLD",
    "rc_DEFECT",
]

RC_STABILITY_PRIOR = {"SHIFT": 0.75, "SETUP": 0.70, "HOLD": 0.55, "DEFECT": 0.65}

MODEL_JOBLIB_NAME = "confidence_classifier.joblib"
MODEL_JSON_NAME = "confidence_classifier.json"


class LogisticRegressionModel:
    """Zero-dependency Logistic Regression (legacy fallback / tiny datasets)."""

    def __init__(self, n_features: int):
        self.weights = np.zeros(n_features)
        self.bias = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 1500, lr: float = 0.1):
        m = len(y)
        for _ in range(epochs):
            z = np.dot(X, self.weights) + self.bias
            h = 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))
            dw = (1.0 / m) * np.dot(X.T, (h - y))
            db = (1.0 / m) * np.sum(h - y)
            self.weights -= lr * dw
            self.bias -= lr * db

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        z = np.dot(X, self.weights) + self.bias
        return 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))


def _safe_div(num: pd.Series | np.ndarray | float, den: pd.Series | np.ndarray | float) -> pd.Series:
    num_s = pd.Series(num, dtype=float)
    den_s = pd.Series(den, dtype=float)
    out = num_s / den_s.replace(0, np.nan)
    return out.fillna(0.0).clip(0.0, 1.0)


def _root_cause_category(rc: object) -> str:
    text = str(rc if rc is not None else "UNKNOWN").upper()
    if "SHIFT" in text or "BREAK" in text:
        return "SHIFT"
    if "SETUP" in text:
        return "SETUP"
    if "HOLD" in text:
        return "HOLD"
    return "DEFECT"


def _enrich_historical_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Derive training features from historical PFA JSON records."""
    work = df.copy()
    work["offset_ratio"] = work["offset_from_scan_in"].astype(float) / work["chain_length"].astype(float).replace(0, np.nan)
    work["offset_ratio"] = work["offset_ratio"].fillna(0.0).clip(0.0, 1.0)
    work["log_pattern_count"] = np.log(1.0 + work["pattern_count"].astype(float))

    pc = work["pattern_consistency"].astype(float).clip(0.0, 1.0)
    work["relative_dominance"] = pc
    max_pat = float(work["pattern_count"].max()) or 1.0
    work["pattern_corroboration"] = (work["pattern_count"].astype(float) / max_pat).clip(0.0, 1.0)
    work["obs_share"] = (
        work["pattern_count"].astype(float) / work["chain_length"].astype(float).replace(0, 234)
    ).clip(0.0, 1.0)
    work["fail_type_consistency"] = (
        work["root_cause_type"].astype(str).str.upper().map(RC_STABILITY_PRIOR).fillna(0.6)
    )

    for rc in ["SHIFT", "SETUP", "HOLD", "DEFECT"]:
        work[f"rc_{rc}"] = (work["root_cause_type"].astype(str).str.upper() == rc).astype(float)

    return work


def _enrich_suspect_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Build ML feature columns from suspect rows (requires evidence_score)."""
    work = df.copy()
    work["pattern_consistency"] = work["evidence_score"].astype(float).clip(0.0, 1.0)

    offset = (
        work["offset_from_scan_in"].astype(float)
        if "offset_from_scan_in" in work.columns
        else pd.Series(0.0, index=work.index)
    )
    length = (
        work["chain_length"].astype(float).replace(0, np.nan)
        if "chain_length" in work.columns
        else pd.Series(1.0, index=work.index)
    )
    work["offset_ratio"] = _safe_div(offset, length.fillna(1.0))

    if "corroborating_patterns" in work.columns:
        work["log_pattern_count"] = np.log(1.0 + work["corroborating_patterns"].astype(float))
    elif "observations" in work.columns:
        work["log_pattern_count"] = np.log(1.0 + work["observations"].astype(float))
    else:
        work["log_pattern_count"] = 0.0

    for col in ("relative_dominance", "pattern_corroboration", "obs_share", "fail_type_consistency"):
        if col not in work.columns:
            work[col] = 0.5
        else:
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.5).clip(0.0, 1.0)

    rc_src = work["predicted_root_cause"] if "predicted_root_cause" in work.columns else "UNKNOWN"
    if isinstance(rc_src, str):
        cats = [_root_cause_category(rc_src)] * len(work)
    else:
        cats = [_root_cause_category(v) for v in rc_src]
    for rc in ["SHIFT", "SETUP", "HOLD", "DEFECT"]:
        work[f"rc_{rc}"] = np.array([1.0 if c == rc else 0.0 for c in cats], dtype=float)

    return work


def _feature_matrix(df: pd.DataFrame, feature_cols: list[str] | None = None) -> np.ndarray:
    cols = feature_cols or FEATURE_COLS
    return df[cols].to_numpy().astype(float)


def _build_sklearn_pipeline(*, calibrate: bool) -> Pipeline | CalibratedClassifierCV:
    base = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "clf",
                GradientBoostingClassifier(
                    n_estimators=300,
                    max_depth=4,
                    learning_rate=0.05,
                    min_samples_leaf=8,
                    subsample=0.85,
                    random_state=42,
                ),
            ),
        ]
    )
    if calibrate:
        return CalibratedClassifierCV(base, cv=5, method="isotonic")
    return base


def train_confidence_model(data_path: str | Path, model_dir: str | Path = "data/models") -> dict:
    """Train calibrated Gradient Boosting on historical PFA confirmation records."""
    data_path = Path(data_path)
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    if not data_path.exists():
        raise FileNotFoundError(f"Historical database not found at {data_path}")

    records = json.loads(data_path.read_text(encoding="utf-8"))
    hist_df = _enrich_historical_frame(pd.DataFrame(records))
    X = _feature_matrix(hist_df)
    y = hist_df["pfa_confirmed"].to_numpy().astype(int)

    calibrate = len(y) >= 30
    estimator = _build_sklearn_pipeline(calibrate=calibrate)
    estimator.fit(X, y)

    bundle = {
        "model_type": "sklearn_gbm_calibrated" if calibrate else "sklearn_gbm",
        "feature_cols": FEATURE_COLS,
        "estimator": estimator,
        "n_train": int(len(y)),
        "positive_rate": float(np.mean(y)),
    }

    joblib_path = model_dir / MODEL_JOBLIB_NAME
    joblib.dump(bundle, joblib_path)

    # Keep legacy JSON metadata for tooling that expects the file to exist
    meta_path = model_dir / MODEL_JSON_NAME
    meta_path.write_text(
        json.dumps(
            {
                "model_type": bundle["model_type"],
                "feature_cols": FEATURE_COLS,
                "n_train": bundle["n_train"],
                "positive_rate": bundle["positive_rate"],
                "joblib": MODEL_JOBLIB_NAME,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "model_type": bundle["model_type"],
        "feature_cols": FEATURE_COLS,
        "n_train": bundle["n_train"],
        "positive_rate": bundle["positive_rate"],
        "estimator": estimator,
    }


def _default_logistic_model() -> dict:
    """Hand-tuned logistic fallback when no historical data or joblib is available."""
    legacy_cols = [
        "pattern_consistency",
        "offset_ratio",
        "log_pattern_count",
        "rc_SHIFT",
        "rc_SETUP",
        "rc_HOLD",
        "rc_DEFECT",
    ]
    return {
        "model_type": "logistic",
        "feature_cols": legacy_cols,
        "means": {c: 0.5 for c in legacy_cols if not c.startswith("rc_")},
        "stds": {c: 1.0 for c in legacy_cols if not c.startswith("rc_")},
        "weights": [2.5, -1.0, 0.8, 1.2, 0.4, -0.4, 0.1],
        "bias": -1.5,
    }


def load_confidence_model(model_dir: str | Path = "data/models") -> dict:
    """Load sklearn GBM bundle, or train from historical PFA data if missing."""
    model_dir = Path(model_dir)
    joblib_path = model_dir / MODEL_JOBLIB_NAME

    if joblib_path.exists():
        bundle = joblib.load(joblib_path)
        if isinstance(bundle, dict) and "estimator" in bundle:
            return bundle

    hist_path = Path("data/historical_pfa_accuracy.json")
    if hist_path.exists():
        return train_confidence_model(hist_path, model_dir)

    json_path = model_dir / MODEL_JSON_NAME
    if json_path.exists():
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        if "weights" in saved:
            saved.setdefault("model_type", "logistic")
            return saved

    return _default_logistic_model()


def compute_evidence_scores(suspects_df: pd.DataFrame) -> pd.DataFrame:
    """Compute corroboration / dominance / consistency evidence features + score."""
    df = suspects_df.copy()
    if df.empty:
        return df

    chain_key = "chain_id" if "chain_id" in df.columns else ("chain" if "chain" in df.columns else None)

    obs = df["observations"].astype(float) if "observations" in df.columns else pd.Series(1.0, index=df.index)
    chain_obs = df["chain_observations"].astype(float) if "chain_observations" in df.columns else obs
    df["obs_share"] = _safe_div(obs, chain_obs)

    if chain_key is not None:
        max_obs = df.groupby(chain_key)["observations"].transform("max").astype(float)
        df["relative_dominance"] = _safe_div(obs, max_obs)
    else:
        df["relative_dominance"] = 1.0

    if "corroborating_patterns" in df.columns:
        patterns = df["corroborating_patterns"].astype(float)
    else:
        patterns = obs

    if "chain_pattern_count" in df.columns:
        chain_pat = df["chain_pattern_count"].astype(float)
        df["pattern_corroboration"] = _safe_div(patterns, chain_pat)
    elif chain_key is not None and "corroborating_patterns" in df.columns:
        max_pat = df.groupby(chain_key)["corroborating_patterns"].transform("max").astype(float)
        df["pattern_corroboration"] = _safe_div(patterns, max_pat)
    elif chain_key is not None:
        max_pat = df.groupby(chain_key)["observations"].transform("max").astype(float)
        df["pattern_corroboration"] = _safe_div(patterns, max_pat)
    else:
        df["pattern_corroboration"] = 1.0

    if "fail_type_consistency" not in df.columns:
        df["fail_type_consistency"] = 0.5
    else:
        df["fail_type_consistency"] = (
            pd.to_numeric(df["fail_type_consistency"], errors="coerce").fillna(0.5).clip(0.0, 1.0)
        )

    df["evidence_score"] = (
        _W_REL_DOM * df["relative_dominance"]
        + _W_PATTERN * df["pattern_corroboration"]
        + _W_OBS_SHARE * df["obs_share"]
        + _W_FAIL_TYPE * df["fail_type_consistency"]
    ).clip(0.0, 1.0)

    return df


def _ml_probabilities_logistic(df: pd.DataFrame, model_data: dict) -> np.ndarray:
    """Legacy logistic regression path (7-feature JSON weights)."""
    work = df.copy()
    work["pattern_consistency"] = work["evidence_score"]
    offset = (
        work["offset_from_scan_in"].astype(float)
        if "offset_from_scan_in" in work.columns
        else pd.Series(0.0, index=work.index)
    )
    length = (
        work["chain_length"].astype(float).replace(0, np.nan)
        if "chain_length" in work.columns
        else pd.Series(1.0, index=work.index)
    )
    work["offset_ratio"] = _safe_div(offset, length.fillna(1.0))
    if "corroborating_patterns" in work.columns:
        work["log_pattern_count"] = np.log(1.0 + work["corroborating_patterns"].astype(float))
    elif "observations" in work.columns:
        work["log_pattern_count"] = np.log(1.0 + work["observations"].astype(float))
    else:
        work["log_pattern_count"] = 0.0

    rc_src = work["predicted_root_cause"] if "predicted_root_cause" in work.columns else "UNKNOWN"
    if isinstance(rc_src, str):
        cats = [_root_cause_category(rc_src)] * len(work)
    else:
        cats = [_root_cause_category(v) for v in rc_src]
    for rc in ["SHIFT", "SETUP", "HOLD", "DEFECT"]:
        work[f"rc_{rc}"] = np.array([1.0 if c == rc else 0.0 for c in cats], dtype=float)

    feature_cols = model_data["feature_cols"]
    X_raw = work[feature_cols].to_numpy().astype(float)
    X_norm = X_raw.copy()
    for idx, col in enumerate(feature_cols):
        if not col.startswith("rc_"):
            mean = model_data["means"].get(col, 0.0)
            std = model_data["stds"].get(col, 1.0) or 1.0
            X_norm[:, idx] = (X_raw[:, idx] - mean) / std

    weights = np.array(model_data["weights"], dtype=float)
    bias = float(model_data["bias"])
    z = np.dot(X_norm, weights) + bias
    return 1.0 / (1.0 + np.exp(-np.clip(z, -20.0, 20.0)))


def _ml_probabilities(df: pd.DataFrame, model_data: dict) -> np.ndarray:
    """Run FR-010 ML layer: sklearn GBM (preferred) or legacy logistic."""
    model_type = model_data.get("model_type", "logistic")

    if model_type.startswith("sklearn") and "estimator" in model_data:
        work = _enrich_suspect_frame(df)
        feature_cols = model_data.get("feature_cols", FEATURE_COLS)
        X = _feature_matrix(work, feature_cols)
        estimator = model_data["estimator"]
        return estimator.predict_proba(X)[:, 1]

    if "weights" in model_data:
        return _ml_probabilities_logistic(df, model_data)

    raise ValueError("Unsupported confidence model bundle")


def _blend_weights(model_data: dict) -> tuple[float, float]:
    model_type = model_data.get("model_type", "logistic")
    if model_type.startswith("sklearn"):
        return _W_EVIDENCE_SKLEARN, _W_ML_SKLEARN
    return _W_EVIDENCE_LOGISTIC, _W_ML_LOGISTIC


def predict_diagnosis_confidence(
    suspects_df: pd.DataFrame,
    model_data: dict | None = None,
) -> pd.DataFrame:
    """Assign calibrated composite confidence to each suspected cell."""
    if suspects_df.empty:
        return suspects_df

    df = compute_evidence_scores(suspects_df)

    ml_probs: np.ndarray | None = None
    w_evidence, w_ml = _W_EVIDENCE_LOGISTIC, _W_ML_LOGISTIC
    if model_data is not None:
        w_evidence, w_ml = _blend_weights(model_data)
        try:
            ml_probs = _ml_probabilities(df, model_data)
        except Exception:
            ml_probs = None

    if ml_probs is not None:
        df["ml_confidence"] = ml_probs
        confidence = w_evidence * df["evidence_score"] + w_ml * df["ml_confidence"]
    else:
        df["ml_confidence"] = np.nan
        confidence = df["evidence_score"]

    out = suspects_df.copy()
    out["obs_share"] = df["obs_share"].round(4)
    out["relative_dominance"] = df["relative_dominance"].round(4)
    out["pattern_corroboration"] = df["pattern_corroboration"].round(4)
    if "fail_type_consistency" in df.columns:
        out["fail_type_consistency"] = df["fail_type_consistency"].round(4)
    out["evidence_score"] = df["evidence_score"].round(4)
    out["ml_confidence"] = df["ml_confidence"].round(4) if ml_probs is not None else df["ml_confidence"]
    out["confidence"] = confidence.clip(0.0, 1.0).round(4)
    return out


def aggregate_diagnosis_confidence(
    suspects_df: pd.DataFrame,
    top_k: int = 1,
) -> dict:
    """Dashboard KPI: fail-weighted mean of per-chain top-1 confidence."""
    empty = {
        "mean_suspect_confidence": None,
        "per_chain_top_mean": None,
        "global_mean_all_suspects": None,
        "max_confidence": None,
        "top_k": top_k,
        "confidence_definition": CONFIDENCE_DEFINITION,
    }
    if suspects_df is None or suspects_df.empty or "confidence" not in suspects_df.columns:
        return empty

    df = suspects_df.copy()
    chain_key = "chain_id" if "chain_id" in df.columns else "chain"
    if chain_key not in df.columns:
        top = df.nlargest(min(top_k, len(df)), "confidence")
        val = float(top["confidence"].mean())
        return {
            "mean_suspect_confidence": round(val, 4),
            "per_chain_top_mean": round(val, 4),
            "global_mean_all_suspects": round(float(df["confidence"].mean()), 4),
            "max_confidence": round(float(df["confidence"].max()), 4),
            "top_k": top_k,
            "confidence_definition": CONFIDENCE_DEFINITION,
        }

    ranked = df.sort_values("confidence", ascending=False)
    top_per_chain = ranked.groupby(chain_key, sort=False).head(top_k)
    chain_top_means = top_per_chain.groupby(chain_key)["confidence"].mean()

    if "chain_observations" in df.columns:
        weights = df.groupby(chain_key)["chain_observations"].first().reindex(chain_top_means.index).astype(float)
        weights = weights.fillna(1.0).clip(lower=1.0)
        weighted = float(np.average(chain_top_means.to_numpy(), weights=weights.to_numpy()))
    else:
        weighted = float(chain_top_means.mean())

    return {
        "mean_suspect_confidence": round(weighted, 4),
        "per_chain_top_mean": round(float(chain_top_means.mean()), 4),
        "global_mean_all_suspects": round(float(df["confidence"].mean()), 4),
        "max_confidence": round(float(df["confidence"].max()), 4),
        "top_k": top_k,
        "confidence_definition": CONFIDENCE_DEFINITION,
    }
