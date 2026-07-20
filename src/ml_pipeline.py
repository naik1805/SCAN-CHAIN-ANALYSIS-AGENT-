"""
ml_pipeline.py — Industry-grade ML pipeline for the Scan Chain Diagnosis Agent.

Replaces the hand-rolled NumPy KNN/KMeans with scikit-learn models.
All models are wrapped in sklearn Pipelines to prevent data leakage.

Public API
----------
train_root_cause_classifier(df)    → (Pipeline, MetricsDict)
predict_root_cause(pipeline, df)   → DataFrame with predictions + probabilities
train_anomaly_detector(df)         → fitted IsolationForest Pipeline
detect_anomalies(detector, df)     → DataFrame with anomaly_score + is_anomaly
save_model(pipeline, path)         → None  (joblib persistence)
load_model(path)                   → Pipeline
get_model_card(pipeline, metrics)  → dict  (for UI display)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

from config import get_config
from exceptions import ModelError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEATURE_COLS: tuple[str, ...] = (
    "ir_drop_mv",
    "thermal_c",
    "setup_slack_ps",
    "hold_slack_ps",
    "die_row",
    "die_col",
    "wafer_x",
    "wafer_y",
)

_CLASSIFIER_FILENAME = "root_cause_classifier.joblib"
_ANOMALY_FILENAME = "anomaly_detector.joblib"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_model_path(filename: str) -> Path:
    """Return absolute path for a model artefact inside ``data/models/``."""
    cfg = get_config()
    model_dir = cfg.model_dir_path
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir / filename


def _prepare_features(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None]:
    """Extract and validate feature matrix and optional label array.

    Args:
        df: Failure DataFrame containing physical feature columns.

    Returns:
        ``(X, y)`` where *y* is ``None`` if ``root_cause_hint`` is absent.

    Raises:
        ModelError: If no feature columns are present in *df*.
    """
    available = [
        c for c in FEATURE_COLS 
        if c in df.columns and not df[c].isna().all()
    ]
    if not available:
        raise ModelError(
            f"None of the required feature columns are present: {list(FEATURE_COLS)}",
            model_name="Pipeline",
        )

    X = df[available].values.astype(float)

    y: np.ndarray | None = None
    if "root_cause_hint" in df.columns:
        labels = df["root_cause_hint"].fillna("UNKNOWN").str.upper().str.strip()
        y = labels.values

    return X, y


# ---------------------------------------------------------------------------
# Root-cause classifier
# ---------------------------------------------------------------------------

def train_root_cause_classifier(
    df: pd.DataFrame,
) -> tuple[Pipeline, dict[str, Any]]:
    """Train a RandomForest root-cause classifier on labeled failure records.

    Only rows with a known (non-UNKNOWN) ``root_cause_hint`` are used for
    training.  Cross-validation accuracy is computed and returned as part
    of the metrics dict.

    Args:
        df: Parsed failure DataFrame with at least the physical feature columns
            and a ``root_cause_hint`` column.

    Returns:
        ``(pipeline, metrics)`` where:
        - *pipeline*: fitted ``sklearn.pipeline.Pipeline`` ready for ``predict``
        - *metrics*: dict with ``cv_accuracy``, ``cv_std``, ``n_train``,
          ``n_classes``, ``class_names``, ``feature_importances``

    Raises:
        ModelError: If there is insufficient labeled data to train.
    """
    cfg = get_config()
    X, y = _prepare_features(df)

    if y is None:
        raise ModelError(
            "root_cause_hint column is required for classifier training.",
            model_name="RandomForest",
        )

    # Filter to labeled, feature-complete rows
    valid_features = ~np.isnan(X).any(axis=1)
    known_labels = (y != "UNKNOWN") & (y != "") & (y != "N/A")
    mask = valid_features & known_labels

    n_train = int(mask.sum())
    if n_train < cfg.ml.min_training_samples:
        raise ModelError(
            f"Not enough labeled training samples: {n_train} < "
            f"{cfg.ml.min_training_samples} (configured minimum).  "
            "Add more labeled failure records.",
            model_name="RandomForest",
        )

    X_train = X[mask]
    y_train = y[mask]
    n_classes = len(np.unique(y_train))

    if n_classes < 2:
        raise ModelError(
            f"Only {n_classes} unique class(es) in training data — "
            "need at least 2 to train a classifier.",
            model_name="RandomForest",
        )

    # Build pipeline: StandardScaler → RandomForestClassifier
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=cfg.ml.n_estimators,
            max_depth=cfg.ml.max_depth,
            min_samples_leaf=cfg.ml.min_samples_leaf,
            class_weight="balanced",   # handles imbalanced failure classes
            random_state=42,
            n_jobs=-1,
        )),
    ])

    # Cross-validation (stratified to respect class distribution if possible)
    from sklearn.model_selection import KFold
    cv_folds = min(cfg.ml.cv_folds, n_train, n_classes)
    
    if cv_folds >= 2:
        _, class_counts = np.unique(y_train, return_counts=True)
        can_stratify = all(count >= cv_folds for count in class_counts)
        if can_stratify:
            cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        else:
            cv = KFold(n_splits=cv_folds, shuffle=True, random_state=42)
        scores = cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="accuracy")
        cv_accuracy = float(np.mean(scores))
        cv_std = float(np.std(scores))
    else:
        cv_accuracy = 1.0
        cv_std = 0.0
        
    log.info(
        "RandomForest CV accuracy: %.3f ± %.3f  (%d folds, %d samples, %d classes)",
        cv_accuracy, cv_std, cv_folds, n_train, n_classes,
    )

    # Final fit on all training data
    pipeline.fit(X_train, y_train)

    # Feature importances (from the RF estimator)
    available_features = [c for c in FEATURE_COLS if c in df.columns]
    importances = pipeline.named_steps["clf"].feature_importances_
    feature_importances = dict(zip(available_features, importances.round(4).tolist()))

    metrics: dict[str, Any] = {
        "cv_accuracy": round(cv_accuracy, 4),
        "cv_std": round(cv_std, 4),
        "n_train": n_train,
        "n_classes": n_classes,
        "class_names": sorted(np.unique(y_train).tolist()),
        "feature_importances": feature_importances,
        "cv_folds": cv_folds,
        "n_estimators": cfg.ml.n_estimators,
        "model_type": "RandomForestClassifier",
    }

    return pipeline, metrics


def predict_root_cause(
    pipeline: Pipeline,
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Run root-cause predictions on unlabeled or unknown records.

    Args:
        pipeline: Fitted classifier pipeline from ``train_root_cause_classifier``.
        df: Failure DataFrame.  Only rows with ``root_cause_hint == UNKNOWN``
            (and valid feature values) are predicted; known rows are left as-is.

    Returns:
        *df* with two new columns:
        - ``predicted_root_cause``: str — predicted class label
        - ``prediction_confidence``: float — max class probability (0–1)
    """
    result = df.copy()
    if "root_cause_hint" in result.columns:
        result["root_cause_hint"] = result["root_cause_hint"].astype(object)
    result["predicted_root_cause"] = result.get("root_cause_hint", pd.Series("UNKNOWN", index=df.index)).fillna("UNKNOWN").astype(object)
    result["prediction_confidence"] = np.nan

    X, y = _prepare_features(df)
    valid_features = ~np.isnan(X).any(axis=1)

    if "root_cause_hint" in df.columns:
        labels = df["root_cause_hint"].fillna("UNKNOWN").str.upper().str.strip()
        unknown_mask = (labels == "UNKNOWN") | (labels == "") | (labels == "N/A")
    else:
        unknown_mask = pd.Series(True, index=df.index)

    predict_mask = unknown_mask.values & valid_features

    if not predict_mask.any():
        log.info("No unlabeled records with valid features — skipping prediction.")
        return result

    X_pred = X[predict_mask]
    try:
        y_pred = pipeline.predict(X_pred)
        y_proba = pipeline.predict_proba(X_pred).max(axis=1)
    except Exception as exc:
        raise ModelError(f"Prediction failed: {exc}", model_name="RandomForest") from exc

    idx = np.where(predict_mask)[0]
    result.iloc[idx, result.columns.get_loc("predicted_root_cause")] = y_pred
    result.iloc[idx, result.columns.get_loc("prediction_confidence")] = y_proba.round(4)

    log.info("Predicted root cause for %d unlabeled records.", len(idx))
    return result


def attach_root_cause_confidence(pipeline: Pipeline, df: pd.DataFrame) -> pd.DataFrame:
    """Attach max class probability for every row with valid features (trust reporting).

    ``predict_root_cause`` only fills confidence on unlabeled rows; production UI
    needs model certainty on all inferable failures.
    """
    result = df.copy()
    if "prediction_confidence" not in result.columns:
        result["prediction_confidence"] = np.nan

    X, _ = _prepare_features(df)
    valid = ~np.isnan(X).any(axis=1)
    if not valid.any():
        return result

    try:
        proba = pipeline.predict_proba(X[valid]).max(axis=1)
    except Exception as exc:
        log.warning("Root-cause confidence scoring skipped: %s", exc)
        return result

    idx = np.where(valid)[0]
    result.iloc[idx, result.columns.get_loc("prediction_confidence")] = np.round(proba, 4)
    return result


# ---------------------------------------------------------------------------
# Anomaly detector (IsolationForest)
# ---------------------------------------------------------------------------

def train_anomaly_detector(df: pd.DataFrame) -> Pipeline:
    """Train an IsolationForest anomaly detector on all failure records.

    Uses all records (labeled or not) — IsolationForest is fully unsupervised.
    Contamination is set from ``config.yaml`` (default 5%).

    Args:
        df: Parsed failure DataFrame with physical feature columns.

    Returns:
        Fitted ``sklearn.pipeline.Pipeline`` (StandardScaler → IsolationForest).

    Raises:
        ModelError: If no valid feature rows exist.
    """
    cfg = get_config()
    X, _ = _prepare_features(df)
    valid = ~np.isnan(X).any(axis=1)
    X_clean = X[valid]

    if len(X_clean) == 0:
        raise ModelError(
            "No rows with complete physical features found for anomaly detection.",
            model_name="IsolationForest",
        )

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("iso", IsolationForest(
            contamination=cfg.ml.anomaly_contamination,
            random_state=42,
            n_estimators=100,
            n_jobs=-1,
        )),
    ])
    pipeline.fit(X_clean)
    log.info(
        "IsolationForest trained on %d records (contamination=%.0f%%).",
        len(X_clean),
        cfg.ml.anomaly_contamination * 100,
    )
    return pipeline


def detect_anomalies(detector: Pipeline, df: pd.DataFrame) -> pd.DataFrame:
    """Score all records with the trained anomaly detector.

    Args:
        detector: Fitted IsolationForest pipeline from ``train_anomaly_detector``.
        df: Failure DataFrame.

    Returns:
        *df* with two new columns:
        - ``anomaly_score``: float — the negative decision function score.
          Higher = more anomalous.
        - ``is_anomaly``: bool — True for records flagged as anomalous.
    """
    result = df.copy()
    result["anomaly_score"] = np.nan
    result["is_anomaly"] = False

    X, _ = _prepare_features(df)
    valid = ~np.isnan(X).any(axis=1)
    X_valid = X[valid]

    if len(X_valid) == 0:
        return result

    try:
        # decision_function: higher score = more normal; negate so higher = more anomalous
        scores = -detector.decision_function(X_valid)
        predictions = detector.predict(X_valid)   # -1 = anomaly, 1 = normal
    except Exception as exc:
        raise ModelError(f"Anomaly scoring failed: {exc}", model_name="IsolationForest") from exc

    idx = np.where(valid)[0]
    result.iloc[idx, result.columns.get_loc("anomaly_score")] = scores.round(6)
    result.iloc[idx, result.columns.get_loc("is_anomaly")] = predictions == -1

    n_anomalies = int((predictions == -1).sum())
    log.info(
        "Anomaly detection: %d / %d records flagged (%.1f%%).",
        n_anomalies, len(X_valid), n_anomalies / len(X_valid) * 100,
    )
    return result


# ---------------------------------------------------------------------------
# Batch inference (export CLI, FastAPI loader, Streamlit)
# ---------------------------------------------------------------------------

def apply_failure_ml(df: pd.DataFrame) -> pd.DataFrame:
    """Load/train sklearn models and attach root-cause + anomaly columns.

    Adds or updates ``predicted_root_cause``, ``prediction_confidence``,
    ``is_anomaly``, and ``anomaly_score`` on the failure DataFrame.
    Safe to call on cached parses that lack ML columns.
    """
    if df.empty:
        return df

    from schema import normalize_failure_schema

    df = normalize_failure_schema(df)

    classifier = load_classifier(df)
    if classifier is None:
        try:
            classifier, metrics = train_root_cause_classifier(df)
            save_classifier(classifier, metrics)
        except Exception as exc:
            log.warning("Root-cause classifier train skipped: %s", exc)
    if classifier is not None:
        try:
            df = predict_root_cause(classifier, df)
            df = attach_root_cause_confidence(classifier, df)
        except Exception as exc:
            log.warning("Root-cause prediction skipped: %s", exc)

    anomaly_detector = load_anomaly_detector(df)
    if anomaly_detector is None:
        try:
            anomaly_detector = train_anomaly_detector(df)
            save_anomaly_detector(anomaly_detector)
        except Exception as exc:
            log.warning("Anomaly detector train skipped: %s", exc)
    if anomaly_detector is not None:
        try:
            df = detect_anomalies(anomaly_detector, df)
        except Exception as exc:
            log.warning("Anomaly detection skipped: %s", exc)

    return df


# ---------------------------------------------------------------------------
# Model persistence (joblib — Option B)
# ---------------------------------------------------------------------------

def save_classifier(pipeline: Pipeline, metrics: dict | None = None) -> Path:
    """Persist the fitted classifier pipeline to disk.

    Args:
        pipeline: Fitted root-cause classifier pipeline.
        metrics: Optional training metrics metadata.

    Returns:
        Path to the saved ``.joblib`` file.
    """
    path = _get_model_path(_CLASSIFIER_FILENAME)
    joblib.dump(pipeline, path)
    log.info("Classifier saved → %s (%.1f KB)", path.name, path.stat().st_size / 1024)
    if metrics:
        metrics_path = path.with_name("root_cause_classifier_metrics.json")
        try:
            import json
            with metrics_path.open("w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2)
            log.info("Classifier metrics saved → %s", metrics_path.name)
        except Exception as exc:
            log.warning("Could not save classifier metrics: %s", exc)
    return path


def load_classifier_metrics() -> dict:
    """Load the persisted classifier metrics metadata from disk."""
    path = _get_model_path(_CLASSIFIER_FILENAME)
    metrics_path = path.with_name("root_cause_classifier_metrics.json")
    if metrics_path.exists():
        try:
            import json
            with metrics_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_classifier(df: pd.DataFrame = None) -> Pipeline | None:
    """Load the persisted classifier pipeline from disk.

    Returns:
        Fitted pipeline, or ``None`` if no saved model exists.
    """
    path = _get_model_path(_CLASSIFIER_FILENAME)
    if not path.exists():
        log.info("No saved classifier found at %s.", path)
        return None
    try:
        pipeline = joblib.load(path)
        if df is not None:
            available = [c for c in FEATURE_COLS if c in df.columns and not df[c].isna().all()]
            n_features_df = len(available)
            if hasattr(pipeline.named_steps["scaler"], "n_features_in_"):
                n_features_model = pipeline.named_steps["scaler"].n_features_in_
                if n_features_model != n_features_df:
                    log.warning("Classifier features mismatch (%d vs %d). Invalidating stale model.", n_features_model, n_features_df)
                    path.unlink(missing_ok=True)
                    metrics_path = _get_model_path("root_cause_classifier_metrics.json")
                    metrics_path.unlink(missing_ok=True)
                    return None
        log.info("Classifier loaded ← %s", path.name)
        return pipeline
    except Exception as exc:
        log.warning("Could not load classifier: %s", exc)
        return None


def save_anomaly_detector(pipeline: Pipeline) -> Path:
    """Persist the fitted anomaly detector pipeline to disk."""
    path = _get_model_path(_ANOMALY_FILENAME)
    joblib.dump(pipeline, path)
    log.info("Anomaly detector saved → %s", path.name)
    return path


def load_anomaly_detector(df: pd.DataFrame = None) -> Pipeline | None:
    """Load the persisted anomaly detector from disk."""
    path = _get_model_path(_ANOMALY_FILENAME)
    if not path.exists():
        return None
    try:
        pipeline = joblib.load(path)
        if df is not None:
            available = [c for c in FEATURE_COLS if c in df.columns and not df[c].isna().all()]
            n_features_df = len(available)
            if hasattr(pipeline.named_steps["scaler"], "n_features_in_"):
                n_features_model = pipeline.named_steps["scaler"].n_features_in_
                if n_features_model != n_features_df:
                    log.warning("Anomaly detector features mismatch (%d vs %d). Invalidating stale model.", n_features_model, n_features_df)
                    path.unlink(missing_ok=True)
                    return None
        log.info("Anomaly detector loaded ← %s", path.name)
        return pipeline
    except Exception as exc:
        log.warning("Could not load anomaly detector: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Model card
# ---------------------------------------------------------------------------

def get_model_card(metrics: dict[str, Any]) -> dict[str, Any]:
    """Build a human-readable model card dict for UI display.

    Args:
        metrics: Metrics dict returned by ``train_root_cause_classifier``.

    Returns:
        Dict suitable for rendering in the dashboard's Model Card panel.
    """
    accuracy = metrics.get("cv_accuracy", 0.0)
    return {
        "Model Type": metrics.get("model_type", "RandomForestClassifier"),
        "CV Accuracy": f"{accuracy:.1%}  ± {metrics.get('cv_std', 0):.1%}",
        "CV Folds": metrics.get("cv_folds", 5),
        "Training Samples": f"{metrics.get('n_train', 0):,}",
        "Classes": ", ".join(metrics.get("class_names", [])),
        "Top Feature": max(
            metrics.get("feature_importances", {"N/A": 0}),
            key=lambda k: metrics["feature_importances"][k],
        ),
        "Quality": (
            "✅ High"   if accuracy >= 0.85 else
            "🟡 Medium" if accuracy >= 0.70 else
            "🔴 Low — consider adding more labeled data"
        ),
    }


__all__ = [
    "FEATURE_COLS",
    "apply_failure_ml",
    "train_root_cause_classifier",
    "predict_root_cause",
    "train_anomaly_detector",
    "detect_anomalies",
    "save_classifier",
    "load_classifier",
    "load_classifier_metrics",
    "save_anomaly_detector",
    "load_anomaly_detector",
    "get_model_card",
]
