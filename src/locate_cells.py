"""
SCD-FR-002 — Locate failing scan cells.

Pipeline:
    1. Parsed log gives, per failure: chain_id, FAIL_FLOP_ID, FAIL_TYPE, signatures.
    2. STIL ScanStructures gives, per chain: scan_length and ordered cell list
       (position <-> cell mapping) plus scan_in / scan_out / clock.
    3. Map the failing flop -> bit position -> cell name using chain length:
           bit_position(from ScanOut) = (flop_number - 1) mod scan_length
           offset_from_scan_in        = scan_length - 1 - bit_position
           cell_name                  = chain.cell_order[bit_position]
    4. Confidence = FR-010 calibrated composite (relative dominance, pattern
       corroboration, obs share, fail-type consistency, blended with ML PFA
       probability) — not a raw observations/chain_observations average.

Output: suspected cell name + position + confidence score per chain.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from stil_parser import resolve_chain

FLOP_NUM_RE = re.compile(r"(\d+)")


def _flop_number(flop_id: str) -> int | None:
    if not isinstance(flop_id, str):
        return None
    m = FLOP_NUM_RE.search(flop_id)
    return int(m.group(1)) if m else None


def enrich_with_positions(failures: pd.DataFrame, chains: dict[str, dict]) -> pd.DataFrame:
    """Add flop_number, chain_length, bit_position, offset_from_scan_in, cell_name.

    Uses STIL chain length per chain; falls back to the log's shift_cycles, then 234.
    """
    df = failures.copy()
    if df.empty:
        for col in ["flop_number", "chain_length", "bit_position",
                    "offset_from_scan_in", "cell_name", "scan_in", "scan_out",
                    "scan_master_clock"]:
            df[col] = pd.Series(dtype="object")
        return df

    df["flop_number"] = df["fail_flop_id"].map(_flop_number)

    # 1. Extract unique (chain_id, chain) combinations
    unique_chains = df[["chain_id", "chain"]].drop_duplicates().copy()
    
    resolved_info = []
    for _, row in unique_chains.iterrows():
        info = resolve_chain(chains, row.get("chain_id", ""), row.get("chain", ""))
        full_id = info.get("chain_id", "") if info else ""
        instance = "core" if "core_inst" in full_id else ("phy" if "phy_inst" in full_id else "other")
        resolved_info.append({
            "chain_id": row["chain_id"],
            "chain": row["chain"],
            "scan_length_stil": info.get("scan_length") if info else None,
            "scan_in": info.get("scan_in") if info else None,
            "scan_out": info.get("scan_out") if info else None,
            "scan_master_clock": info.get("scan_master_clock") if info else None,
            "instance": instance,
            "_info_obj": info
        })
    info_df = pd.DataFrame(resolved_info)
    df = df.merge(info_df, on=["chain_id", "chain"], how="left")

    # 2. Vectorized calculations
    shift_cycles = (
        df["shift_cycles"]
        if "shift_cycles" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    df["chain_length"] = df["scan_length_stil"].fillna(shift_cycles).fillna(234).astype(int)

    mask_valid = df["flop_number"].notna()
    df["bit_position"] = np.nan
    df.loc[mask_valid, "bit_position"] = (df.loc[mask_valid, "flop_number"] - 1) % df.loc[mask_valid, "chain_length"]

    df["offset_from_scan_in"] = np.nan
    mask_bp = df["bit_position"].notna()
    df.loc[mask_bp, "offset_from_scan_in"] = df.loc[mask_bp, "chain_length"] - 1 - df.loc[mask_bp, "bit_position"]

    # 3. Unique (chain_id, bit_position) lookup for cell names
    unique_bp = df[mask_bp][["chain_id", "chain", "bit_position", "_info_obj"]].drop_duplicates(subset=["chain_id", "chain", "bit_position"]).copy()
    
    cell_names = []
    for _, row in unique_bp.iterrows():
        info = row["_info_obj"]
        bp = int(row["bit_position"])
        name = None
        if info and 0 <= bp < len(info.get("cell_order", [])):
            name = info["cell_order"][bp]
        elif info and info.get("hierarchical_path"):
            name = f"{info['hierarchical_path']}[{bp}]"
        else:
            chain_id = row.get('chain_id', row['chain'])
            num_match = re.search(r'(?:channel|chain_?|ch_?)(\d+)', chain_id, re.IGNORECASE)
            if num_match:
                val = int(num_match.group(1))
                idx = val - 1 if "channel" in num_match.group(0).lower() else val
                name = f"U_core/reg_c{idx}_ff[{bp}]"
            else:
                name = f"{chain_id}.sff_{bp:03d}"
        cell_names.append({
            "chain_id": row["chain_id"],
            "chain": row["chain"],
            "bit_position": row["bit_position"],
            "cell_name": name
        })
    cell_name_df = pd.DataFrame(cell_names)
    
    if not cell_name_df.empty:
        df = df.merge(cell_name_df, on=["chain_id", "chain", "bit_position"], how="left")
    else:
        df["cell_name"] = None

    df = df.drop(columns=["scan_length_stil", "_info_obj"])
    return df


def _mode_or_none(s: pd.Series):
    s = s.dropna()
    if s.empty:
        return None
    m = s.mode()
    return m.iloc[0] if not m.empty else None


def _instance_of(chain_id: str) -> str:
    cid = chain_id or ""
    if "core_inst" in cid:
        return "core"
    if "phy_inst" in cid:
        return "phy"
    return "other"


def locate_failing_cells(
    failures: pd.DataFrame,
    chains: dict[str, dict],
    min_observations: int = 1,
) -> pd.DataFrame:
    """Return suspected failing scan cells with a confidence score (SCD-FR-002).

    One row per physical (chain_id, fail_flop_id/cell). Grouping is by FULL chain
    id so that same-numbered chains in different instances (e.g. core vs phy
    channel1) are not merged.

    Confidence is the FR-010 calibrated composite from ``confidence_score``:
    evidence (relative dominance, pattern corroboration, obs share, fail-type
    consistency) blended with isotonic-calibrated Gradient Boosting P(PFA) — not a
    raw observations/chain_observations average.
    """
    cols = ["chain", "instance", "chain_id", "cell_name", "fail_flop_id",
            "bit_position", "offset_from_scan_in", "chain_length", "observations",
            "corroborating_patterns", "chain_observations", "chain_pattern_count",
            "fail_type_consistency", "confidence",
            "obs_share", "relative_dominance", "pattern_corroboration",
            "evidence_score", "ml_confidence",
            "dominant_fail_type", "dominant_region", "dominant_root_cause",
            "predicted_root_cause", "mean_ai_severity", "lots_affected", "scan_in", "scan_out",
            "scan_master_clock",
            "mean_ir_drop", "mean_temp", "mean_setup_slack", "mean_hold_slack"]

    enriched = enrich_with_positions(failures, chains)
    if enriched.empty:
        return pd.DataFrame(columns=cols)

    # Root-cause prediction: skip inline KNN when failures already carry
    # ``predicted_root_cause`` from ml_pipeline (RandomForest — API / export path).
    if "predicted_root_cause" not in enriched.columns:
        enriched["predicted_root_cause"] = enriched["root_cause_hint"].fillna("UNKNOWN")
        
        features_cols = ["ir_drop_mv", "thermal_c", "setup_slack_ps", "hold_slack_ps"]
        if all(col in enriched.columns for col in features_cols):
            # We need rows with valid features and non-unknown labels
            cleaned_labels = enriched["root_cause_hint"].fillna("UNKNOWN").str.upper().str.strip()
            labeled_mask = (cleaned_labels != "UNKNOWN") & (cleaned_labels != "") & (cleaned_labels != "N/A")
            valid_features_mask = enriched[features_cols].notna().all(axis=1)
            
            train_mask = labeled_mask & valid_features_mask
            
            if train_mask.sum() >= 5:
                X_train = enriched.loc[train_mask, features_cols].values
                y_train = cleaned_labels[train_mask].values
                
                # Ensure we have at least 2 unique classes in training data
                if len(np.unique(y_train)) > 1:
                    from ml_models import StandardScaler, KNNClassifier
                    scaler = StandardScaler()
                    X_train_scaled = scaler.fit_transform(X_train)
                    
                    knn = KNNClassifier()
                    knn.fit(X_train_scaled, y_train)
                    
                    predict_mask = (~labeled_mask) & valid_features_mask
                    if predict_mask.any():
                        X_pred = enriched.loc[predict_mask, features_cols].values
                        X_pred_scaled = scaler.transform(X_pred)
                        y_pred = knn.predict(X_pred_scaled, k=min(5, len(y_train)))
                        
                        enriched.loc[predict_mask, "predicted_root_cause"] = y_pred

    def get_mode_df(col_name, target_col):
        valid = enriched[["chain_id", "fail_flop_id", col_name]].dropna()
        if valid.empty:
            df_modes = enriched[["chain_id", "fail_flop_id"]].drop_duplicates().copy()
            df_modes[target_col] = None
            return df_modes
        counts = valid.groupby(["chain_id", "fail_flop_id", col_name]).size().rename("count").reset_index()
        # Sort by count desc, then by col_name asc (alphabetical tie-breaker)
        modes = counts.sort_values(["count", col_name], ascending=[False, True]).drop_duplicates(subset=["chain_id", "fail_flop_id"]).rename(columns={col_name: target_col})
        return modes[["chain_id", "fail_flop_id", target_col]]

    mode_fail_type = get_mode_df("fail_type", "dominant_fail_type")
    mode_region = get_mode_df("failure_region", "dominant_region")
    mode_root_cause = get_mode_df("root_cause_hint", "dominant_root_cause")
    mode_pred_root = get_mode_df("predicted_root_cause", "predicted_root_cause")

    # 2. Main group aggregation with fast compiled functions
    grouped = enriched.groupby(["chain_id", "fail_flop_id"], dropna=False)
    agg_res = grouped.agg(
        chain=("chain", "first"),
        instance=("instance", "first"),
        cell_name=("cell_name", "first"),
        bit_position=("bit_position", "first"),
        offset_from_scan_in=("offset_from_scan_in", "first"),
        chain_length=("chain_length", "first"),
        observations=("chain_id", "size"),
        corroborating_patterns=("pattern_id", "nunique"),
        severity_sum=("ai_severity_score", "sum"),
        severity_count=("ai_severity_score", "count"),
        lots_affected=("lot_id", "nunique"),
        scan_in=("scan_in", "first"),
        scan_out=("scan_out", "first"),
        scan_master_clock=("scan_master_clock", "first"),
        mean_ir_drop=("ir_drop_mv", "mean"),
        mean_temp=("thermal_c", "mean"),
        mean_setup_slack=("setup_slack_ps", "mean"),
        mean_hold_slack=("hold_slack_ps", "mean"),
    ).reset_index()

    # Calculate mean using sum / count
    agg_res["mean_ai_severity"] = np.nan
    mask_count = agg_res["severity_count"] > 0
    agg_res.loc[mask_count, "mean_ai_severity"] = agg_res.loc[mask_count, "severity_sum"] / agg_res.loc[mask_count, "severity_count"]
    agg_res = agg_res.drop(columns=["severity_sum", "severity_count"])

    # Merge the modes back
    agg_res = agg_res.merge(mode_fail_type, on=["chain_id", "fail_flop_id"], how="left")
    agg_res = agg_res.merge(mode_region, on=["chain_id", "fail_flop_id"], how="left")
    agg_res = agg_res.merge(mode_root_cause, on=["chain_id", "fail_flop_id"], how="left")
    agg_res = agg_res.merge(mode_pred_root, on=["chain_id", "fail_flop_id"], how="left")

    if min_observations > 1:
        agg_res = agg_res[agg_res["observations"] >= min_observations]

    if agg_res.empty:
        return pd.DataFrame(columns=cols)

    chain_obs = enriched.groupby("chain_id").size().rename("chain_observations")
    agg_res = agg_res.merge(chain_obs, on="chain_id", how="left")

    if "pattern_id" in enriched.columns:
        chain_pat = enriched.groupby("chain_id")["pattern_id"].nunique().rename("chain_pattern_count")
        agg_res = agg_res.merge(chain_pat, on="chain_id", how="left")
    else:
        agg_res["chain_pattern_count"] = agg_res["corroborating_patterns"]

    # Fail-type consistency: fraction of this cell's observations matching its mode
    if "fail_type" in enriched.columns and "dominant_fail_type" in agg_res.columns:
        ft_join = enriched[["chain_id", "fail_flop_id", "fail_type"]].merge(
            agg_res[["chain_id", "fail_flop_id", "dominant_fail_type"]],
            on=["chain_id", "fail_flop_id"],
            how="left",
        )
        ft_join["ft_match"] = (
            ft_join["fail_type"].astype(str) == ft_join["dominant_fail_type"].astype(str)
        )
        ft_cons = (
            ft_join.groupby(["chain_id", "fail_flop_id"])["ft_match"]
            .mean()
            .rename("fail_type_consistency")
            .reset_index()
        )
        agg_res = agg_res.merge(ft_cons, on=["chain_id", "fail_flop_id"], how="left")
        agg_res["fail_type_consistency"] = agg_res["fail_type_consistency"].fillna(0.5)
    else:
        agg_res["fail_type_consistency"] = 0.5

    # Seed obs_share for transparency; FR-010 composite overwrites confidence
    agg_res["confidence"] = (agg_res["observations"] / agg_res["chain_observations"]).round(4)

    # Calibrated composite confidence (SCD-FR-010) — evidence + ML, no artificial floor
    try:
        from confidence_score import load_confidence_model, predict_diagnosis_confidence
        model_data = load_confidence_model()
        scored = predict_diagnosis_confidence(agg_res, model_data)
        for col in (
            "confidence", "obs_share", "relative_dominance", "pattern_corroboration",
            "evidence_score", "ml_confidence", "fail_type_consistency",
        ):
            if col in scored.columns:
                agg_res[col] = scored[col]
    except Exception:
        # Evidence-only fallback if model load / predict fails
        try:
            from confidence_score import predict_diagnosis_confidence
            scored = predict_diagnosis_confidence(agg_res, None)
            agg_res["confidence"] = scored["confidence"]
            if "fail_type_consistency" in scored.columns:
                agg_res["fail_type_consistency"] = scored["fail_type_consistency"]
        except Exception:
            pass

    # Round mean_ai_severity using two-stage rounding to eliminate float representation noise
    agg_res["mean_ai_severity"] = agg_res["mean_ai_severity"].map(lambda x: round(round(float(x), 10), 3) if pd.notna(x) else None)

    # Cast/map bit_position and offset_from_scan_in
    agg_res["bit_position"] = agg_res["bit_position"].map(lambda x: int(x) if pd.notna(x) else None)
    agg_res["offset_from_scan_in"] = agg_res["offset_from_scan_in"].map(lambda x: int(x) if pd.notna(x) else None)

    agg_res = agg_res.sort_values(
        ["confidence", "observations"], ascending=False
    ).reset_index(drop=True)

    # Only return declared columns that exist (extra score diagnostics kept if present
    # would break callers expecting exact cols — stick to cols list)
    return agg_res[[c for c in cols if c in agg_res.columns]]
