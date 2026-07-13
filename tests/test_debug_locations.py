"""test_debug_locations.py — Unit tests for coordinate recommendation (SCD-FR-009)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from debug_locations import calculate_cell_coordinates, export_pfa_locations


class TestCalculateCellCoordinates:
    def test_empty_df_returns_empty(self, minimal_chain_map):
        empty_df = pd.DataFrame(columns=["lot_id", "chain_id", "chain",
                                          "fail_flop_id", "shift_cycles"])
        result = calculate_cell_coordinates(empty_df, minimal_chain_map)
        assert result.empty

    def test_returns_coordinates_dataframe(self, minimal_failures_df, minimal_chain_map):
        # Inject log coordinates (x1, y1, x2, y2)
        df = minimal_failures_df.copy()
        df["x1"] = 100.0
        df["y1"] = 100.0
        df["x2"] = 104.0
        df["y2"] = 104.0
        df["wafer_x"] = 102.0
        df["wafer_y"] = 102.0
        df["die_label"] = "fail_die_1"
        
        result = calculate_cell_coordinates(df, minimal_chain_map)
        assert isinstance(result, pd.DataFrame)
        if not result.empty:
            assert "x_local_um" in result.columns
            assert "y_local_um" in result.columns
            assert "priority" in result.columns
            assert "occurrences" in result.columns
            
            # Check local coordinate range (0 to 4000 microns)
            assert (result["x_local_um"] >= 0).all()
            assert (result["x_local_um"] <= 4000.0).all()
            assert (result["y_local_um"] >= 0).all()
            assert (result["y_local_um"] <= 4000.0).all()
            
            # Check occurrence values
            occ = result["occurrences"].iloc[0]
            assert isinstance(occ, list)
            assert len(occ) > 0
            assert "wafer_x_mm" in occ[0]
            assert "wafer_y_mm" in occ[0]
            assert occ[0]["wafer_x_mm"] >= 100.0
            assert occ[0]["wafer_x_mm"] <= 104.0


class TestExportPfaLocations:
    def test_export_empty_dataframe(self, tmp_path):
        empty_df = pd.DataFrame()
        res = export_pfa_locations(empty_df, tmp_path)
        assert res["status"] == "no_suspects_found"
        assert (tmp_path / "SCD-FR-009_debug_locations.json").exists()
        assert (tmp_path / "SCD-FR-009_debug_locations.csv").exists()

    def test_export_valid_dataframe(self, tmp_path):
        coords_data = [
            {
                "cell_name": "cell_1",
                "chain": "channel1",
                "fail_flop_id": "FF_1",
                "offset_from_scan_in": 10,
                "bit_position": 10,
                "x_local_um": 500.5,
                "y_local_um": 1200.2,
                "confidence": 0.95,
                "predicted_root_cause": "SCAN_SHIFT",
                "priority": "High",
                "distinct_dies_affected": 2,
                "occurrences": [
                    {"lot_id": "LOT_1", "die_label": "fail_die_1", "wafer_x_mm": 100.5, "wafer_y_mm": 101.2},
                    {"lot_id": "LOT_1", "die_label": "fail_die_2", "wafer_x_mm": 100.5, "wafer_y_mm": 101.2}
                ]
            }
        ]
        coords_df = pd.DataFrame(coords_data)
        res = export_pfa_locations(coords_df, tmp_path)
        assert res["status"] == "satisfied"
        assert res["summary"]["total_recommended_cells"] == 1
        assert res["summary"]["high_priority_count"] == 1
        
        # Verify file contents
        assert (tmp_path / "SCD-FR-009_debug_locations.json").exists()
        assert (tmp_path / "SCD-FR-009_debug_locations.csv").exists()
