"""Production holdout validation — lot-grouped trust metrics for fab readiness."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

_CACHE_NAME = "holdout_validation.json"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _cache_path() -> Path:
    return _project_root() / "data" / "cache" / _CACHE_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lot_key(df: pd.DataFrame) -> str | None:
    for col in ("lot_id", "lot", "LOT_ID"):
        if col in df.columns:
            return col
    return None


def _break_certain_rate(breaks: list[dict[str, Any]] | pd.DataFrame) -> dict[str, Any]:
    if isinstance(breaks, pd.DataFrame):
        rows = breaks.to_dict(orient="records") if not breaks.empty else []
    else:
        rows = list(breaks or [])
    n = len(rows)
    if n == 0:
        return {"total": 0, "certain": 0, "uncertain": 0, "certain_pct": None}
    certain = sum(1 for r in rows if str(r.get("location_status", "")).upper() == "CERTAIN")
    return {
        "total": n,
        "certain": certain,
        "uncertain": n - certain,
        "certain_pct": round(100.0 * certain / n, 1),
    }


def _top1_multi_lot_consensus(suspects: pd.DataFrame) -> dict[str, Any]:
    """Share of chains whose top cell appears in ≥2 lots (when lot evidence exists)."""
    if suspects is None or suspects.empty:
        return {"chains_scored": 0, "multi_lot_top1_pct": None, "multi_lot_top1_count": 0}

    chain_key = "chain_id" if "chain_id" in suspects.columns else "chain"
    if chain_key not in suspects.columns or "confidence" not in suspects.columns:
        return {"chains_scored": 0, "multi_lot_top1_pct": None, "multi_lot_top1_count": 0}

    work = suspects.sort_values("confidence", ascending=False)
    top1 = work.groupby(chain_key, sort=False).head(1)
    n_chains = len(top1)

    # Prefer explicit lots_affected; else cannot score multi-lot
    if "lots_affected" in top1.columns:
        multi = int((pd.to_numeric(top1["lots_affected"], errors="coerce").fillna(1) >= 2).sum())
    else:
        return {"chains_scored": n_chains, "multi_lot_top1_pct": None, "multi_lot_top1_count": 0}

    return {
        "chains_scored": n_chains,
        "multi_lot_top1_count": multi,
        "multi_lot_top1_pct": round(100.0 * multi / n_chains, 1) if n_chains else None,
    }


def _stratified_row_holdout(failures: pd.DataFrame) -> dict[str, Any]:
    """80/20 stratified holdout by label — measures within-class generalization."""
    empty = {
        "available": False,
        "holdout_accuracy_pct": None,
        "holdout_mean_confidence_pct": None,
        "n_holdout": 0,
        "n_train": 0,
        "note": "Stratified holdout unavailable",
    }
    if failures is None or failures.empty or "root_cause_hint" not in failures.columns:
        return empty

    try:
        from ml_pipeline import _prepare_features
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        empty["note"] = f"Stratified deps unavailable: {exc}"
        return empty

    work = failures.copy()
    labels = work["root_cause_hint"].fillna("UNKNOWN").astype(str).str.upper().str.strip()
    known = ~labels.isin({"UNKNOWN", "", "N/A"})
    work = work.loc[known].copy()
    y = work["root_cause_hint"].fillna("UNKNOWN").astype(str).str.upper().str.strip()
    if len(work) < 40 or y.nunique() < 2:
        empty["note"] = "Not enough labeled diversity for stratified holdout"
        return empty

    # Drop classes with < 4 samples (can't stratify)
    vc = y.value_counts()
    keep = y.isin(vc[vc >= 4].index)
    work = work.loc[keep]
    y = y.loc[keep]
    if len(work) < 40:
        empty["note"] = "Too few rows after filtering rare classes"
        return empty

    idx = np.arange(len(work))
    try:
        tr_idx, te_idx = train_test_split(
            idx, test_size=0.2, random_state=42, stratify=y.to_numpy()
        )
    except ValueError:
        tr_idx, te_idx = train_test_split(idx, test_size=0.2, random_state=42)

    train_df = work.iloc[tr_idx]
    test_df = work.iloc[te_idx]
    X_train, _ = _prepare_features(train_df)
    X_test, _ = _prepare_features(test_df)
    y_train = train_df["root_cause_hint"].fillna("UNKNOWN").astype(str).str.upper().str.strip().to_numpy()
    y_test = test_df["root_cause_hint"].fillna("UNKNOWN").astype(str).str.upper().str.strip().to_numpy()

    valid_tr = ~np.isnan(X_train).any(axis=1)
    valid_te = ~np.isnan(X_test).any(axis=1)
    if valid_tr.sum() < 20 or valid_te.sum() < 5:
        empty["note"] = "Incomplete features in stratified split"
        return empty

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=120,
            max_depth=10,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )),
    ])
    pipe.fit(X_train[valid_tr], y_train[valid_tr])
    pred = pipe.predict(X_test[valid_te])
    acc = float(np.mean(pred == y_test[valid_te]))
    proba = pipe.predict_proba(X_test[valid_te]).max(axis=1)
    return {
        "available": True,
        "holdout_accuracy_pct": round(acc * 100, 1),
        "holdout_mean_confidence_pct": round(float(proba.mean()) * 100, 1),
        "n_holdout": int(valid_te.sum()),
        "n_train": int(valid_tr.sum()),
        "n_classes": int(len(np.unique(y_train[valid_tr]))),
        "note": "Stratified 80/20 holdout by root-cause class (known defect modes).",
    }


def _lot_holdout_root_cause(failures: pd.DataFrame) -> dict[str, Any]:
    """Train RF on ~80% of lots; score accuracy on held-out lots (grouped by lot)."""
    empty = {
        "available": False,
        "holdout_accuracy_pct": None,
        "holdout_lots": [],
        "train_lots": [],
        "n_holdout": 0,
        "n_train": 0,
        "unseen_classes_in_holdout": [],
        "note": "Insufficient labeled lot groups for holdout",
    }
    if failures is None or failures.empty:
        return empty

    lot_col = _lot_key(failures)
    if lot_col is None:
        empty["note"] = "No lot_id column — cannot run lot holdout"
        return empty

    try:
        from ml_pipeline import _prepare_features
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        empty["note"] = f"Holdout deps unavailable: {exc}"
        return empty

    work = failures.copy()
    label_col = "root_cause_hint" if "root_cause_hint" in work.columns else None
    if label_col is None:
        empty["note"] = "No root_cause_hint labels for holdout"
        return empty

    labels = work[label_col].fillna("UNKNOWN").astype(str).str.upper().str.strip()
    known = ~labels.isin({"UNKNOWN", "", "N/A"})
    work = work.loc[known].copy()
    if len(work) < 40:
        empty["note"] = f"Too few labeled rows ({len(work)}) for holdout"
        return empty

    lots = sorted(work[lot_col].astype(str).unique().tolist())
    if len(lots) < 3:
        empty["note"] = f"Need ≥3 lots for holdout (have {len(lots)})"
        return empty

    # Hold out ~20% of lots (at least 1)
    n_hold = max(1, int(round(len(lots) * 0.2)))
    hold_lots = lots[-n_hold:]
    train_lots = [L for L in lots if L not in hold_lots]

    train_mask = work[lot_col].astype(str).isin(train_lots)
    test_mask = work[lot_col].astype(str).isin(hold_lots)
    train_df = work.loc[train_mask]
    test_df = work.loc[test_mask]
    if len(train_df) < 20 or len(test_df) < 5:
        empty["note"] = "Holdout split too small after lot partition"
        return empty

    train_classes = set(
        train_df[label_col].fillna("UNKNOWN").astype(str).str.upper().str.strip().unique()
    )
    test_classes = set(
        test_df[label_col].fillna("UNKNOWN").astype(str).str.upper().str.strip().unique()
    )
    unseen = sorted(test_classes - train_classes)

    X_train, _ = _prepare_features(train_df)
    X_test, _ = _prepare_features(test_df)
    y_train = train_df[label_col].fillna("UNKNOWN").astype(str).str.upper().str.strip().to_numpy()
    y_test = test_df[label_col].fillna("UNKNOWN").astype(str).str.upper().str.strip().to_numpy()

    valid_tr = ~np.isnan(X_train).any(axis=1)
    valid_te = ~np.isnan(X_test).any(axis=1)
    if valid_tr.sum() < 20 or valid_te.sum() < 5:
        empty["note"] = "Too many incomplete feature rows in holdout split"
        return empty

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=120,
            max_depth=10,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )),
    ])
    pipe.fit(X_train[valid_tr], y_train[valid_tr])
    pred = pipe.predict(X_test[valid_te])
    acc = float(np.mean(pred == y_test[valid_te]))
    proba = pipe.predict_proba(X_test[valid_te]).max(axis=1)

    note = (
        f"Lot-holdout RF trained on {len(train_lots)} lots, "
        f"tested on {len(hold_lots)} unseen lot(s)."
    )
    if unseen:
        note += (
            f" Holdout lots contain unseen classes {unseen} — "
            "accuracy will be near zero until those modes appear in training."
        )

    return {
        "available": True,
        "holdout_accuracy_pct": round(acc * 100, 1),
        "holdout_mean_confidence_pct": round(float(proba.mean()) * 100, 1),
        "holdout_lots": hold_lots,
        "train_lots": train_lots,
        "n_holdout": int(valid_te.sum()),
        "n_train": int(valid_tr.sum()),
        "n_classes_train": int(len(np.unique(y_train[valid_tr]))),
        "unseen_classes_in_holdout": unseen,
        "note": note,
    }


def compute_production_validation(
    failures: pd.DataFrame,
    suspects: pd.DataFrame | list[dict[str, Any]],
    breaks: list[dict[str, Any]] | pd.DataFrame,
    *,
    fingerprint: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Aggregate fab-readiness metrics; cache by data fingerprint."""
    suspects_df = suspects if isinstance(suspects, pd.DataFrame) else pd.DataFrame(suspects or [])
    cache_file = _cache_path()

    if use_cache and fingerprint and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                return cached
        except Exception:
            pass

    holdout = _lot_holdout_root_cause(failures)
    stratified = _stratified_row_holdout(failures)
    breaks_meta = _break_certain_rate(breaks)
    consensus = _top1_multi_lot_consensus(suspects_df)

    # Production readiness: prefer stratified (known classes); lot-holdout is a risk flag
    parts: list[tuple[float, float]] = []  # (weight, score 0-1)
    primary_acc = stratified.get("holdout_accuracy_pct")
    if primary_acc is None:
        primary_acc = holdout.get("holdout_accuracy_pct")
    if primary_acc is not None:
        parts.append((0.40, float(primary_acc) / 100.0))
    if consensus.get("multi_lot_top1_pct") is not None:
        parts.append((0.25, float(consensus["multi_lot_top1_pct"]) / 100.0))
    if breaks_meta.get("certain_pct") is not None:
        certain = float(breaks_meta["certain_pct"]) / 100.0
        parts.append((0.15, min(1.0, certain * 2.0)))
    if not suspects_df.empty and "confidence" in suspects_df.columns:
        top = suspects_df.sort_values("confidence", ascending=False)
        chain_key = "chain_id" if "chain_id" in top.columns else "chain"
        if chain_key in top.columns:
            top1 = top.groupby(chain_key, sort=False).head(1)
            parts.append((0.20, float(pd.to_numeric(top1["confidence"], errors="coerce").mean())))

    readiness = round(100.0 * sum(w * s for w, s in parts) / sum(w for w, _ in parts), 1) if parts else None

    if readiness is None:
        grade = "unknown"
    elif readiness >= 75:
        grade = "production_ready"
    elif readiness >= 55:
        grade = "pilot_ready"
    else:
        grade = "needs_hardening"

    # Escalate grade warning when lot-holdout exposes unseen defect modes
    unseen = holdout.get("unseen_classes_in_holdout") or []
    if unseen and grade == "production_ready":
        grade = "pilot_ready"

    report = {
        "fingerprint": fingerprint,
        "generated_at": _now_iso(),
        "readiness_score_pct": readiness,
        "readiness_grade": grade,
        "lot_holdout": holdout,
        "stratified_holdout": stratified,
        "break_localization": breaks_meta,
        "top1_consensus": consensus,
        "client_summary": _summary_text(readiness, grade, holdout, stratified, breaks_meta, consensus),
    }

    if use_cache and fingerprint:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("Could not cache holdout validation: %s", exc)

    return report


def _summary_text(
    readiness: float | None,
    grade: str,
    holdout: dict[str, Any],
    stratified: dict[str, Any],
    breaks_meta: dict[str, Any],
    consensus: dict[str, Any],
) -> str:
    bits = []
    if readiness is not None:
        bits.append(f"Production readiness {readiness:.0f}% ({grade.replace('_', ' ')}).")
    if stratified.get("available"):
        bits.append(
            f"Stratified holdout accuracy {stratified['holdout_accuracy_pct']}% "
            f"on known defect classes."
        )
    if holdout.get("available"):
        unseen = holdout.get("unseen_classes_in_holdout") or []
        if unseen:
            bits.append(
                f"Unseen-lot risk: holdout lots introduce {unseen} "
                f"(lot accuracy {holdout.get('holdout_accuracy_pct')}%)."
            )
        else:
            bits.append(
                f"Lot-holdout accuracy {holdout['holdout_accuracy_pct']}% "
                f"on {len(holdout.get('holdout_lots') or [])} unseen lot(s)."
            )
    if breaks_meta.get("total"):
        bits.append(
            f"Break localization: {breaks_meta['certain']}/{breaks_meta['total']} CERTAIN "
            f"({breaks_meta.get('certain_pct')}%)."
        )
    if consensus.get("multi_lot_top1_pct") is not None:
        bits.append(
            f"Top-1 cells confirmed across ≥2 lots: {consensus['multi_lot_top1_pct']}%."
        )
    return " ".join(bits) if bits else "Production validation pending — load labeled multi-lot data."
