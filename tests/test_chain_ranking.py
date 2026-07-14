"""Tests for SCD-FR-004 native pandas Series.rank() ranking."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from chain_ranking import (
    DEFAULT_RANK_METHOD,
    RANK_METHODS,
    available_ranking_features,
    rank_chains_by_frequency,
)


def test_available_ranking_features_lists_all_methods():
    info = available_ranking_features()
    assert info["api"] == "pandas.Series.rank"
    assert set(info["methods"]) == set(RANK_METHODS)
    assert info["default_method"] == "dense"


def test_rank_chains_uses_native_series_rank():
    df = pd.DataFrame({
        "chain": ["c1", "c1", "c1", "c2", "c2", "c3"],
    })
    ranked = rank_chains_by_frequency(df, method="dense")
    assert list(ranked["chain"]) == ["c1", "c2", "c3"]
    assert list(ranked["rank"]) == [1, 2, 3]
    assert ranked.iloc[0]["fail_count"] == 3
    assert ranked.iloc[0]["rank_method"] == "dense"


def test_rank_methods_handle_ties():
    df = pd.DataFrame({"chain": ["a", "a", "b", "b", "c"]})
    dense = rank_chains_by_frequency(df, method="dense")
    # a and b both have 2 fails → both rank 1 with dense? No - dense: both get min rank 1, next is 2
    # Actually dense with ascending=False: a=2, b=2 → both rank 1; c=1 → rank 2
    assert set(dense.loc[dense["fail_count"] == 2, "rank"]) == {1}
    assert int(dense.loc[dense["chain"] == "c", "rank"].iloc[0]) == 2

    average = rank_chains_by_frequency(df, method="average")
    # tied a,b get average of ranks 1 and 2 = 1.5
    tied = average.loc[average["fail_count"] == 2, "rank"]
    assert all(float(x) == 1.5 for x in tied)


def test_unknown_method_raises():
    df = pd.DataFrame({"chain": ["x"]})
    with pytest.raises(ValueError):
        rank_chains_by_frequency(df, method="not_a_method")
