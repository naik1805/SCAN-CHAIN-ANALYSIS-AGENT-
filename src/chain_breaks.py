"""
SCD-FR-006 — Exact scan-chain break localization.

A hard shift-path break at flip-flop N (bit index from ScanOut) causes:
  - bits 0 .. N-1  → shift out correctly (pass / no care mismatch)
  - bits N .. L-1  → fail on unload

Exact location is therefore the **first mismatching bit** on the unload
stream, taken as the consensus across failing patterns (not a single global
min that can be skewed by one noisy pattern).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from locate_cells import enrich_with_positions
from stil_parser import resolve_chain

# Production certainty gate: only claim an exact cell when pattern agreement is high.
LOCATION_CERTAIN_SOFT_MIN = 0.70
LOCATION_CERTAIN_MIN_PATTERNS = 2


def _last_care_index(expected_bs: str | None, chain_length: int) -> int:
    if expected_bs and isinstance(expected_bs, str):
        last_care = len(expected_bs) - 1
        while last_care >= 0 and expected_bs[last_care] == "X":
            last_care -= 1
        if last_care >= 0:
            return last_care
    return max(chain_length - 1, 0)


def compute_break_location_confidence(
    firsts: pd.Series,
    exact_bit: int,
    *,
    upstream_coverage: float,
    downstream_fail_frac: float,
    patterns_total: int,
    tolerance: int = 5,
) -> dict:
    """
    Genuine FR-006 location confidence metrics for production test use.

    ``location_confidence`` = soft agreement: fraction of failing patterns whose
    first EXPECTED/ACTUAL mismatch bit falls within ±tolerance of the reported
    break bit. No artificial floor or inflation — weak agreement stays weak so
    a fab/test engineer does not over-trust a noisy localization.
    """
    empty = {
        "location_confidence": 0.0,
        "exact_agreement": 0.0,
        "soft_agreement": 0.0,
        "frontier_consistent": 0.0,
        "downstream_clean_score": 0.0,
        "coverage_score": 0.0,
        "evidence_score": 0.0,
        "concentration_score": 0.0,
        "first_mismatch_std": None,
        "confidence_definition": (
            f"soft_agreement: share of patterns with first_mismatch in "
            f"[exact_bit-{tolerance}, exact_bit+{tolerance}]"
        ),
    }
    if firsts is None or len(firsts) == 0:
        return empty

    firsts = pd.to_numeric(firsts, errors="coerce").dropna().astype(int)
    exact_agreement = float((firsts == exact_bit).mean())
    soft_agreement = float(
        ((firsts >= exact_bit - tolerance) & (firsts <= exact_bit + tolerance)).mean()
    )
    frontier_consistent = float((firsts >= max(exact_bit - tolerance, 0)).mean())

    if len(firsts) >= 2:
        spread = float(firsts.std(ddof=0))
        concentration_score = float(np.clip(1.0 - (spread / 40.0), 0.0, 1.0))
        median_first = float(firsts.median())
        proximity = float(np.clip(1.0 - abs(exact_bit - median_first) / 12.0, 0.0, 1.0))
        concentration_score = 0.6 * concentration_score + 0.4 * proximity
        first_mismatch_std = round(spread, 3)
    else:
        concentration_score = 1.0
        first_mismatch_std = 0.0

    downstream_clean_score = float(np.clip(1.0 - (downstream_fail_frac / 0.15), 0.0, 1.0))
    coverage_score = float(np.clip(upstream_coverage / 0.35, 0.0, 1.0))
    evidence_score = float(np.clip(patterns_total / 6.0, 0.0, 1.0))

    # Primary reported confidence = measurable soft agreement (no floor)
    location_confidence = soft_agreement

    return {
        "location_confidence": round(location_confidence, 4),
        "exact_agreement": round(exact_agreement, 4),
        "soft_agreement": round(soft_agreement, 4),
        "frontier_consistent": round(frontier_consistent, 4),
        "downstream_clean_score": round(downstream_clean_score, 4),
        "coverage_score": round(coverage_score, 4),
        "evidence_score": round(evidence_score, 4),
        "concentration_score": round(concentration_score, 4),
        "first_mismatch_std": first_mismatch_std,
        "confidence_definition": empty["confidence_definition"],
    }


def _cell_at_bit(sub: pd.DataFrame, chain_map: dict, chain_id: str, chain: str, bit: int) -> str:
    match = sub[sub["bit_position"] == bit] if "bit_position" in sub.columns else pd.DataFrame()
    if not match.empty and "cell_name" in match.columns and pd.notna(match["cell_name"].iloc[0]):
        return str(match["cell_name"].iloc[0])

    info = resolve_chain(chain_map, chain_id, chain) if chain_map else None
    if info:
        order = info.get("cell_order") or []
        if 0 <= bit < len(order):
            return order[bit]
        path = info.get("hierarchical_path")
        if path:
            return f"{path}[{bit}]"
    return f"Unknown_FF[{bit}]"


def locate_exact_break_for_group(
    sub: pd.DataFrame,
    chain_map: dict | None = None,
    *,
    min_patterns: int = 1,
    min_unique_positions: int = 5,
    max_downstream_fail_frac: float = 0.15,
) -> dict | None:
    """
    Return the exact break location for one (die, chain) failure group, or None.

    Detection gate (is there a break?):
      - Downstream of ScanOut has few/no fails, failures extend to SI/care end,
        and enough distinct failing positions.

    Exact location:
      - Consensus (mode) of per-pattern first EXPECTED vs ACTUAL mismatch bits.
      - Fallback: median of per-pattern first mismatches, then global min fail bit.
    """
    if sub.empty or "bit_position" not in sub.columns:
        return None

    positions = pd.to_numeric(sub["bit_position"], errors="coerce").dropna()
    if positions.empty:
        return None

    chain_length = int(sub["chain_length"].iloc[0]) if "chain_length" in sub.columns else 234
    exp0 = (
        sub["expected_output"].iloc[0]
        if "expected_output" in sub.columns and pd.notna(sub["expected_output"].iloc[0])
        else None
    )
    max_care = _last_care_index(exp0, chain_length)

    if "pattern_id" in sub.columns:
        firsts = (
            sub.assign(bit_position=pd.to_numeric(sub["bit_position"], errors="coerce"))
            .dropna(subset=["bit_position"])
            .groupby("pattern_id")["bit_position"]
            .min()
            .astype(int)
        )
    else:
        firsts = pd.Series([int(positions.min())])

    if firsts.empty:
        return None

    unique_pos = int(positions.nunique())
    max_pos = int(positions.max())
    min_pos = int(positions.min())
    patterns_total = int(len(firsts))

    # --- Gate: classic hard-break signature (coverage), not overly strict ---
    downstream_fail_frac_global = float((positions < min_pos).sum() / max(len(positions), 1))
    # min_pos is global min; for gate use whether fails start after SO and reach end
    looks_like_break = (
        min_pos > 0
        and max_pos >= (max_care - 5)
        and unique_pos >= min_unique_positions
        and patterns_total >= min_patterns
        and downstream_fail_frac_global <= max_downstream_fail_frac
    )
    if not looks_like_break:
        return None

    # --- Exact location from per-pattern first-mismatch consensus ---
    counts = firsts.value_counts()
    mode_bit = int(counts.index[0])
    agreement = float(counts.iloc[0] / len(firsts))
    patterns_agreeing = int(counts.iloc[0])
    median_bit = int(firsts.median())

    if agreement >= 0.5:
        exact_bit = mode_bit
        method = "per_pattern_first_mismatch_consensus"
    elif patterns_total >= 3:
        exact_bit = median_bit
        method = "per_pattern_first_mismatch_median"
        agreement = float((firsts == exact_bit).mean())
        patterns_agreeing = int((firsts == exact_bit).sum())
    else:
        # Few patterns: exact unload frontier = that pattern's first mismatch
        # (or the shared min if multiple)
        exact_bit = mode_bit if patterns_total == 1 else min(int(firsts.min()), mode_bit)
        # Prefer the minimum first-mismatch among patterns (earliest SO-side frontier)
        exact_bit = int(firsts.min())
        method = "per_pattern_first_mismatch_min"
        agreement = float((firsts == exact_bit).mean())
        patterns_agreeing = int((firsts == exact_bit).sum())

    # Safety: exact bit must be a real mid-chain frontier
    if exact_bit <= 0:
        exact_bit = min_pos
        method = "contiguous_fail_frontier"

    span = list(range(exact_bit, max_care + 1))
    failed_set = set(positions.astype(int).tolist())
    covered = sum(1 for p in span if p in failed_set)
    upstream_coverage = covered / max(len(span), 1)
    downstream_fail_frac = float((positions < exact_bit).sum() / max(len(positions), 1))

    conf_parts = compute_break_location_confidence(
        firsts,
        exact_bit,
        upstream_coverage=upstream_coverage,
        downstream_fail_frac=downstream_fail_frac,
        patterns_total=patterns_total,
        tolerance=5,
    )
    # Soft-agreeing patterns (±5 bits)
    soft_tol = 5
    patterns_agreeing_soft = int(
        ((firsts >= exact_bit - soft_tol) & (firsts <= exact_bit + soft_tol)).sum()
    )

    location_certain = (
        conf_parts["soft_agreement"] >= LOCATION_CERTAIN_SOFT_MIN
        and patterns_total >= LOCATION_CERTAIN_MIN_PATTERNS
    )
    location_status = "CERTAIN" if location_certain else "UNCERTAIN"
    location_status_reason = (
        f"soft_agreement {conf_parts['soft_agreement']:.1%} >= {LOCATION_CERTAIN_SOFT_MIN:.0%} "
        f"with {patterns_total} patterns"
        if location_certain
        else (
            f"soft_agreement {conf_parts['soft_agreement']:.1%} < {LOCATION_CERTAIN_SOFT_MIN:.0%} "
            f"and/or patterns ({patterns_total}) < {LOCATION_CERTAIN_MIN_PATTERNS} — "
            "break detected; exact break bit not confirmed across patterns"
        )
    )

    chain = sub["chain"].iloc[0]
    chain_id = sub["chain_id"].iloc[0] if "chain_id" in sub.columns else ""
    lot = sub["lot_id"].iloc[0] if "lot_id" in sub.columns else None
    sf = sub["source_file"].iloc[0] if "source_file" in sub.columns else None

    cell_name = _cell_at_bit(sub, chain_map or {}, chain_id, chain, exact_bit)
    info = resolve_chain(chain_map or {}, chain_id, chain)
    scan_in = info.get("scan_in") if info else "Unknown"
    scan_out = info.get("scan_out") if info else "Unknown"
    offset_from_si = chain_length - 1 - exact_bit

    prev_cell = _cell_at_bit(sub, chain_map or {}, chain_id, chain, exact_bit - 1) if exact_bit > 0 else None
    next_cell = (
        _cell_at_bit(sub, chain_map or {}, chain_id, chain, exact_bit + 1)
        if exact_bit < chain_length - 1 else None
    )

    bitstream_patterns = []
    if "pattern_id" in sub.columns:
        for p_id, p_sub in sub.groupby("pattern_id"):
            exp_bs = (
                p_sub["expected_output"].iloc[0]
                if "expected_output" in p_sub.columns and pd.notna(p_sub["expected_output"].iloc[0])
                else None
            )
            act_bs = (
                p_sub["actual_output"].iloc[0]
                if "actual_output" in p_sub.columns and pd.notna(p_sub["actual_output"].iloc[0])
                else None
            )
            mismatches = sorted(
                pd.to_numeric(p_sub["bit_position"], errors="coerce").dropna().astype(int).unique().tolist()
            )
            first_mm = int(min(mismatches)) if mismatches else None
            bitstream_patterns.append({
                "pattern_id": str(p_id),
                "expected_bitstream": exp_bs,
                "actual_bitstream": act_bs,
                "mismatches": mismatches,
                "first_mismatch_bit": first_mm,
                "agrees_with_exact_break": first_mm == exact_bit,
                "soft_agrees_with_exact_break": (
                    first_mm is not None and abs(first_mm - exact_bit) <= soft_tol
                ),
            })

    return {
        "source_file": Path(sf).name if sf else sf,
        "lot_id": lot,
        "chain": chain,
        "chain_id": chain_id,
        "chain_length": int(chain_length),
        # Always keep candidate localization for schematics / review
        "candidate_break_bit_position": int(exact_bit),
        "candidate_break_cell": cell_name,
        # Production-safe "exact" fields — only when CERTAIN
        "break_bit_position": int(exact_bit),
        "exact_break_bit_position": int(exact_bit) if location_certain else None,
        "exact_break_cell": cell_name if location_certain else "LOCATION_UNCERTAIN",
        "suspected_break_cell": cell_name,
        "location_status": location_status,
        "location_status_reason": location_status_reason,
        "offset_from_scan_in": int(offset_from_si),
        "downstream_cell_toward_so": prev_cell,
        "upstream_cell_toward_si": next_cell,
        "location_confidence": conf_parts["location_confidence"],
        "exact_agreement": conf_parts["exact_agreement"],
        "soft_agreement": conf_parts["soft_agreement"],
        "first_mismatch_std": conf_parts.get("first_mismatch_std"),
        "confidence_definition": conf_parts.get("confidence_definition"),
        "localization_method": method,
        "patterns_agreeing": patterns_agreeing_soft,
        "patterns_agreeing_exact": patterns_agreeing,
        "patterns_analyzed": patterns_total,
        "upstream_coverage": round(upstream_coverage, 4),
        "downstream_fail_fraction": round(downstream_fail_frac, 4),
        "fail_count": int(len(sub)),
        "unique_failing_positions": unique_pos,
        "scan_in": scan_in,
        "scan_out": scan_out,
        "expected_actual_bitstreams": bitstream_patterns,
    }


def detect_chain_breaks(
    failures: pd.DataFrame,
    chain_map: dict | None = None,
) -> pd.DataFrame:
    """Detect exact break locations for every (lot, die, chain) group."""
    empty_cols = [
        "source_file", "lot_id", "chain", "chain_id", "chain_length",
        "break_bit_position", "candidate_break_bit_position", "candidate_break_cell",
        "exact_break_bit_position", "exact_break_cell",
        "suspected_break_cell", "location_status", "location_status_reason",
        "offset_from_scan_in",
        "downstream_cell_toward_so", "upstream_cell_toward_si",
        "location_confidence", "exact_agreement", "soft_agreement",
        "first_mismatch_std", "localization_method",
        "patterns_agreeing", "patterns_analyzed",
        "upstream_coverage", "downstream_fail_fraction",
        "fail_count", "unique_failing_positions", "scan_in", "scan_out",
    ]
    if failures is None or failures.empty:
        return pd.DataFrame(columns=empty_cols)

    enriched = enrich_with_positions(failures, chain_map or {})
    if enriched.empty:
        return pd.DataFrame(columns=empty_cols)

    breaks = []
    grouped = enriched.groupby(["source_file", "lot_id", "chain"], dropna=False)
    for _, sub in grouped:
        result = locate_exact_break_for_group(sub, chain_map or {})
        if result:
            # Drop bulky bitstream list from the DataFrame view (kept in JSON export)
            row = {k: v for k, v in result.items() if k != "expected_actual_bitstreams"}
            breaks.append(row)

    res = pd.DataFrame(breaks)
    if not res.empty:
        res = res.sort_values(by=["lot_id", "source_file", "chain"]).reset_index(drop=True)
    return res


def detect_chain_breaks_detailed(
    failures: pd.DataFrame,
    chain_map: dict | None = None,
) -> list[dict]:
    """Same as detect_chain_breaks but returns full dicts including bitstreams."""
    if failures is None or failures.empty:
        return []

    enriched = enrich_with_positions(failures, chain_map or {})
    if enriched.empty:
        return []

    breaks = []
    grouped = enriched.groupby(["source_file", "lot_id", "chain"], dropna=False)
    for _, sub in grouped:
        result = locate_exact_break_for_group(sub, chain_map or {})
        if result:
            breaks.append(result)
    breaks.sort(key=lambda x: (str(x.get("lot_id")), str(x.get("source_file")), str(x.get("chain"))))
    return breaks
