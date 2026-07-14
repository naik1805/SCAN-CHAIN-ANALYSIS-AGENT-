"""
SCD-FR-004 — Native pandas ranking helpers for scan-chain failure frequency.

Uses ``Series.rank()`` (pandas native ranking API) rather than positional
index assignment after sort.
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Available Series.rank() features (pandas native ranking API)
# ---------------------------------------------------------------------------
RANK_METHODS = {
    "average": "Tied values share the average of their ordinal ranks (default in pandas).",
    "min": "Tied values all get the lowest (best) rank of the group (competition ranking).",
    "max": "Tied values all get the highest (worst) rank of the group.",
    "first": "Ties broken by order of appearance in the Series (stable, no shared ranks).",
    "dense": "Like min, but ranks always increase by 1 between distinct groups (no gaps).",
}

RANK_OPTIONS = {
    "ascending": "False → higher fail_count gets better (lower) rank number.",
    "na_option": "How to rank NaNs: 'keep' | 'top' | 'bottom'.",
    "pct": "If True, return percentile ranks in [0, 1] instead of ordinal ranks.",
}

# Default for FR-004: dense competition ranking, highest failure count = rank 1
DEFAULT_RANK_METHOD = "dense"


def available_ranking_features() -> dict:
    """Return the catalog of native ranking features used / available."""
    return {
        "api": "pandas.Series.rank",
        "default_method": DEFAULT_RANK_METHOD,
        "methods": dict(RANK_METHODS),
        "options": dict(RANK_OPTIONS),
        "fr004_usage": {
            "column_ranked": "fail_count",
            "method": DEFAULT_RANK_METHOD,
            "ascending": False,
            "pct": False,
            "meaning": "Chains with more failures receive lower rank numbers (1 = worst).",
        },
    }


def rank_chains_by_frequency(
    df: pd.DataFrame,
    method: str = DEFAULT_RANK_METHOD,
    pct: bool = False,
) -> pd.DataFrame:
    """
    Aggregate failure counts per chain and apply native ``Series.rank()``.

    FR-004 uses ``method='dense'`` (default): highest fail_count → rank 1,
    ties share a rank, and the next distinct count gets the next integer
    with no gaps.
    """
    empty_cols = ["chain", "fail_count", "fail_pct", "cumulative_pct", "rank", "rank_method"]
    if df.empty or "chain" not in df.columns:
        return pd.DataFrame(columns=empty_cols)

    # FR-004 locks to dense ranking unless an explicit alternate is requested
    if method is None:
        method = DEFAULT_RANK_METHOD
    if method not in RANK_METHODS:
        raise ValueError(
            f"Unknown rank method {method!r}. Choose from: {', '.join(RANK_METHODS)}"
        )

    freq = (
        df.groupby("chain", sort=False)
        .size()
        .reset_index(name="fail_count")
    )
    total = int(freq["fail_count"].sum())
    freq["fail_pct"] = (freq["fail_count"] / total * 100).round(3) if total else 0.0

    # Native pandas ranking: higher fail_count → better (lower) ordinal rank
    ranks = freq["fail_count"].rank(method=method, ascending=False, pct=pct)
    if pct:
        freq["rank"] = ranks.round(6)
    elif method == "average":
        # average may produce half-ranks (e.g. 1.5) for ties
        freq["rank"] = ranks
    else:
        freq["rank"] = ranks.astype(int)

    freq["rank_method"] = method

    # Sort display order by rank, then fail_count for stable tables
    freq = freq.sort_values(
        by=["rank", "fail_count", "chain"],
        ascending=[True, False, True],
    ).reset_index(drop=True)

    freq["cumulative_pct"] = freq["fail_pct"].cumsum().round(3)
    return freq
