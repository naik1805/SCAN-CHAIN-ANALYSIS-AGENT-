"""Model lifecycle — auto-retrain when engineer feedback accumulates."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_STATE_NAME = "model_lifecycle.json"
DEFAULT_FEEDBACK_RETRAIN_THRESHOLD = 25


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    return _project_root() / "data" / "cache" / _STATE_NAME


def _models_dir() -> Path:
    return _project_root() / "data" / "models"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_lifecycle_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {
            "last_retrain_at": None,
            "last_feedback_count": 0,
            "last_result": None,
            "retrain_threshold": DEFAULT_FEEDBACK_RETRAIN_THRESHOLD,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "last_retrain_at": None,
            "last_feedback_count": 0,
            "last_result": None,
            "retrain_threshold": DEFAULT_FEEDBACK_RETRAIN_THRESHOLD,
        }


def save_lifecycle_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _merge_pfa_training_file() -> Path:
    """Merge historical PFA JSON + engineer feedback into a train file."""
    from review_queue import load_feedback_records

    hist_path = _project_root() / "data" / "historical_pfa_accuracy.json"
    out_path = _project_root() / "data" / "cache" / "pfa_train_merged.json"

    hist: list = []
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []

    feedback = load_feedback_records()
    # Keep only feature fields the confidence trainer expects
    merged = list(hist)
    for row in feedback:
        merged.append({
            "pattern_consistency": row.get("pattern_consistency", 0.5),
            "offset_from_scan_in": row.get("offset_from_scan_in", 0),
            "chain_length": row.get("chain_length", 234),
            "pattern_count": row.get("pattern_count", 1),
            "root_cause_type": row.get("root_cause_type", "DEFECT"),
            "pfa_confirmed": int(row.get("pfa_confirmed", 0)),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return out_path


def should_retrain(*, threshold: int | None = None) -> dict[str, Any]:
    from review_queue import feedback_count

    state = load_lifecycle_state()
    thr = int(threshold or state.get("retrain_threshold") or DEFAULT_FEEDBACK_RETRAIN_THRESHOLD)
    n_fb = feedback_count()
    last_n = int(state.get("last_feedback_count") or 0)
    due = n_fb >= thr and n_fb > last_n
    return {
        "due": due,
        "feedback_count": n_fb,
        "last_feedback_count_at_retrain": last_n,
        "threshold": thr,
        "new_since_retrain": max(0, n_fb - last_n),
    }


def maybe_retrain(
    failures=None,
    *,
    force: bool = False,
    threshold: int | None = None,
) -> dict[str, Any]:
    """Retrain cell-confidence GBM (and optionally RF) when feedback threshold met."""
    check = should_retrain(threshold=threshold)
    if not force and not check["due"]:
        return {
            "retrained": False,
            "reason": "threshold_not_met",
            **check,
        }

    result: dict[str, Any] = {
        "retrained": False,
        "reason": "started",
        **check,
        "steps": [],
    }

    # 1) Cell confidence GBM from merged PFA + engineer feedback
    try:
        from confidence_score import train_confidence_model

        train_path = _merge_pfa_training_file()
        # Backup previous joblib
        models = _models_dir()
        joblib_path = models / "confidence_classifier.joblib"
        if joblib_path.exists():
            bak = models / f"confidence_classifier_backup_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.joblib"
            shutil.copy2(joblib_path, bak)
            result["steps"].append(f"backed_up_gbm:{bak.name}")

        metrics = train_confidence_model(train_path, models)
        result["steps"].append(
            f"gbm_trained:n={metrics.get('n_train')},pos={metrics.get('positive_rate')}"
        )
        result["gbm"] = {
            "n_train": metrics.get("n_train"),
            "positive_rate": metrics.get("positive_rate"),
            "model_type": metrics.get("model_type"),
        }
        result["retrained"] = True
    except Exception as exc:
        log.exception("GBM retrain failed")
        result["steps"].append(f"gbm_failed:{exc}")
        result["gbm_error"] = str(exc)

    # 2) Optional RF retrain when failures provided
    if failures is not None:
        try:
            import ml_pipeline as mlp

            clf_path = mlp._get_model_path(mlp._CLASSIFIER_FILENAME)
            if clf_path.exists():
                bak = clf_path.with_name(
                    f"root_cause_classifier_backup_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.joblib"
                )
                shutil.copy2(clf_path, bak)
                result["steps"].append(f"backed_up_rf:{bak.name}")
                clf_path.unlink(missing_ok=True)

            pipeline, metrics = mlp.train_root_cause_classifier(failures)
            mlp.save_classifier(pipeline, metrics)
            result["steps"].append(
                f"rf_trained:cv={metrics.get('cv_accuracy')},n={metrics.get('n_train')}"
            )
            result["random_forest"] = {
                "cv_accuracy": metrics.get("cv_accuracy"),
                "n_train": metrics.get("n_train"),
            }
            result["retrained"] = True
        except Exception as exc:
            log.exception("RF retrain failed")
            result["steps"].append(f"rf_failed:{exc}")
            result["rf_error"] = str(exc)

    state = load_lifecycle_state()
    if result["retrained"]:
        state["last_retrain_at"] = _now_iso()
        state["last_feedback_count"] = check["feedback_count"]
        state["last_result"] = {
            "gbm": result.get("gbm"),
            "random_forest": result.get("random_forest"),
            "steps": result.get("steps"),
        }
        if threshold is not None:
            state["retrain_threshold"] = int(threshold)
        save_lifecycle_state(state)
        result["reason"] = "completed"
    else:
        result["reason"] = "failed"

    result["lifecycle"] = load_lifecycle_state()
    return result


def lifecycle_summary() -> dict[str, Any]:
    state = load_lifecycle_state()
    check = should_retrain()
    return {
        **state,
        "retrain_due": check["due"],
        "feedback_count": check["feedback_count"],
        "new_since_retrain": check["new_since_retrain"],
        "threshold": check["threshold"],
    }
