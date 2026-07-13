"""test_locate_cells.py — Unit tests for failing-cell localization (SCD-FR-002)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from locate_cells import locate_failing_cells, enrich_with_positions


class TestEnrichWithPositions:
    def test_adds_bit_position_column(self, minimal_failures_df, minimal_chain_map):
        enriched = enrich_with_positions(minimal_failures_df, minimal_chain_map)
        assert "bit_position" in enriched.columns

    def test_adds_cell_name_column(self, minimal_failures_df, minimal_chain_map):
        enriched = enrich_with_positions(minimal_failures_df, minimal_chain_map)
        assert "cell_name" in enriched.columns

    def test_bit_position_within_chain_length(self, minimal_failures_df, minimal_chain_map):
        enriched = enrich_with_positions(minimal_failures_df, minimal_chain_map)
        valid = enriched["bit_position"].dropna()
        assert (valid >= 0).all()
        assert (valid < 234).all()   # chain length = 234

    def test_empty_df_returns_empty(self, minimal_chain_map):
        empty_df = pd.DataFrame(columns=["lot_id", "chain_id", "chain",
                                          "fail_flop_id", "shift_cycles"])
        result = enrich_with_positions(empty_df, minimal_chain_map)
        assert result.empty

    def test_no_chain_map_still_works(self, minimal_failures_df):
        # With empty chain_map, should fall back to shift_cycles or 234
        enriched = enrich_with_positions(minimal_failures_df, {})
        assert "bit_position" in enriched.columns


class TestLocateFailingCells:
    def test_returns_dataframe(self, minimal_failures_df, minimal_chain_map):
        result = locate_failing_cells(minimal_failures_df, minimal_chain_map)
        assert isinstance(result, pd.DataFrame)

    def test_required_output_columns(self, minimal_failures_df, minimal_chain_map):
        result = locate_failing_cells(minimal_failures_df, minimal_chain_map)
        required = {"chain", "chain_id", "cell_name", "fail_flop_id",
                    "bit_position", "observations", "confidence"}
        assert required.issubset(set(result.columns))

    def test_confidence_between_0_and_1(self, minimal_failures_df, minimal_chain_map):
        result = locate_failing_cells(minimal_failures_df, minimal_chain_map)
        if not result.empty:
            assert (result["confidence"] >= 0.0).all()
            assert (result["confidence"] <= 1.0).all()

    def test_sorted_by_confidence_desc(self, minimal_failures_df, minimal_chain_map):
        result = locate_failing_cells(minimal_failures_df, minimal_chain_map)
        if len(result) > 1:
            assert result["confidence"].iloc[0] >= result["confidence"].iloc[-1]

    def test_min_observations_filter(self, minimal_failures_df, minimal_chain_map):
        result_low = locate_failing_cells(minimal_failures_df, minimal_chain_map, min_observations=1)
        result_high = locate_failing_cells(minimal_failures_df, minimal_chain_map, min_observations=100)
        # Higher threshold should return fewer or equal rows
        assert len(result_high) <= len(result_low)

    def test_empty_failures_returns_empty(self, minimal_chain_map):
        empty_df = pd.DataFrame(columns=["lot_id", "chain_id", "chain",
                                          "fail_flop_id", "shift_cycles",
                                          "root_cause_hint"])
        result = locate_failing_cells(empty_df, minimal_chain_map)
        assert result.empty
