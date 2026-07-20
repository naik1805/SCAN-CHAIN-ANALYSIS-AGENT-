"""Regression tests for FastAPI diagnosis_service (live path must not silently break)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(scope="module")
def diagnosis_service():
    from adapters import diagnosis_service as ds

    return ds


class TestDiagnosisServiceStructure:
    """Catch edits that orphan helpers (e.g. NameError on _classify_shift_capture)."""

    def test_critical_helpers_exist(self, diagnosis_service):
        for name in (
            "_classify_shift_capture",
            "_breaks_distribution_by_lot",
            "_build_correlation_rows",
            "_build_from_live",
            "get_dashboard",
            "get_kpi_workspace",
        ):
            assert hasattr(diagnosis_service, name), f"missing {name}"

    def test_breaks_distribution_by_lot_sorted_desc(self, diagnosis_service):
        rows = diagnosis_service._breaks_distribution_by_lot([
            {"lot_id": "LOT_2"},
            {"lot_id": "LOT_7"},
            {"lot_id": "LOT_7"},
            {"lot_id": "LOT_3"},
        ])
        assert rows == [
            {"lot_id": "LOT_7", "scan_chain_break_count": 2},
            {"lot_id": "LOT_2", "scan_chain_break_count": 1},
            {"lot_id": "LOT_3", "scan_chain_break_count": 1},
        ]

    def test_classify_shift_capture_empty(self, diagnosis_service):
        import pandas as pd

        out = diagnosis_service._classify_shift_capture(pd.DataFrame(), pd.DataFrame())
        assert out["total"] == 0


class TestDiagnosisServiceLive:
    """Live dashboard must match discovered logs — not stale export JSON."""

    def test_validate_live_path_passes(self, diagnosis_service):
        from adapters.data_loader import load_failures, select_logs

        expected_logs = len(select_logs(max_per_lot=None))
        failures_df, _ = load_failures(max_per_lot=None)
        expected_failures = len(failures_df)

        result = diagnosis_service.validate_live_path()
        assert result["ok"] is True, result.get("errors")
        assert result["expected_log_count"] == expected_logs
        assert result["expected_failure_records"] == expected_failures
        assert result["failure_records"] == expected_failures
        assert result["log_file_count"] == expected_logs

    def test_live_dashboard_matches_loader(self, diagnosis_service):
        from adapters.data_loader import load_failures, select_logs

        expected_logs = len(select_logs(max_per_lot=None))
        failures_df, _ = load_failures(max_per_lot=None)
        expected_failures = len(failures_df)

        dash = diagnosis_service.get_dashboard(mode="live")
        assert dash.data_source == "fastapi-live", dash.footer
        assert "export JSON artifacts" not in dash.footer
        assert "NameError" not in dash.footer
        assert dash.dataset_summary.total_failure_records == expected_failures
        assert dash.dataset_summary.log_file_count == expected_logs

    def test_mock_mode_uses_live_engine(self, diagnosis_service):
        """Legacy mock mode must not return decorative fake KPIs."""
        from adapters.data_loader import load_failures, select_logs

        expected_logs = len(select_logs(max_per_lot=None))
        failures_df, _ = load_failures(max_per_lot=None)
        expected_failures = len(failures_df)

        dash = diagnosis_service.get_dashboard(mode="mock")
        assert dash.data_source == "fastapi-live", dash.footer
        assert dash.dataset_summary.total_failure_records == expected_failures
        assert dash.dataset_summary.log_file_count == expected_logs
        assert dash.footer != "Data source: Mock JSON"

    def test_chain_breaks_workspace_has_lot_distribution(self, diagnosis_service):
        ws = diagnosis_service.get_kpi_workspace("chain_breaks", mode="live")
        kinds = [p.kind for p in ws.panels]
        assert "breaks_by_lot" in kinds
        assert "break_visualizer" in kinds
        assert "breaks_table" in kinds
        lot_panel = next(p for p in ws.panels if p.kind == "breaks_by_lot")
        assert lot_panel.title == "Breaks Distribution by Lot"

    def test_shift_capture_workspace_has_diagnostics_registry(self, diagnosis_service):
        ws = diagnosis_service.get_kpi_workspace("shift_capture", mode="live")
        kinds = [p.kind for p in ws.panels]
        assert "shift_capture" in kinds
        assert "diagnostics_registry" in kinds
        reg = next(p for p in ws.panels if p.kind == "diagnostics_registry")
        assert reg.title == "Diagnostics Registry Table"
        assert len(reg.table) > 0
        row = reg.table[0]
        assert "classification" in row
        assert "diagnosis_details" in row
        assert "lot_id" in row

    def test_topology_workspace_has_full_fr003_panels(self, diagnosis_service):
        ws = diagnosis_service.get_kpi_workspace("topology_chains", mode="live")
        kinds = [p.kind for p in ws.panels]
        for expected in (
            "topology_overview",
            "topology_chain_balance",
            "topology_shared_resources",
            "topology_compression",
            "topology_registry",
            "topology_connectivity",
            "topology_schematic",
        ):
            assert expected in kinds, f"missing panel {expected}"
        reg = next(p for p in ws.panels if p.kind == "topology_registry")
        assert len(reg.table) >= 1
        assert "scan_input_si" in reg.table[0]
        schematic = next(p for p in ws.panels if p.kind == "topology_schematic")
        assert len(schematic.meta.get("chains") or []) >= 1

    def test_failure_correlations_workspace_has_chain_signature_panels(self, diagnosis_service):
        ws = diagnosis_service.get_kpi_workspace("failure_correlations", mode="live")
        kinds = [p.kind for p in ws.panels]
        assert kinds.index("chain_signature_overview") < kinds.index("chain_signature_profile")
        assert "chain_signature_overview" in kinds
        assert "chain_signature_profile" in kinds
        assert "correlation_chain_averages" in kinds
        assert "correlation_heatmap" not in kinds
        assert "correlation_matrix" not in kinds

        profile = next(p for p in ws.panels if p.kind == "chain_signature_profile")
        overview = next(p for p in ws.panels if p.kind == "chain_signature_overview")
        assert profile.title == "Chain Signature Profile"
        assert overview.title == "Chain Signature Overview"
        assert len(profile.table) >= 1
        assert len(overview.table) >= 1

        row = profile.table[0]
        assert "chain" in row
        assert "metric_comparisons" in row
        assert "distinguishing_factors" in row
        assert "signature_bullets" in row
        assert "physical_timing_percentages" in row
        assert "spatial_percentages" in row
        assert "chain_averages" in row
        assert profile.meta.get("signature_method")
        assert profile.meta.get("chain_signature_overview")
        assert profile.meta.get("region_field_used") == "die_label"
    def test_debug_locations_workspace_has_full_table_and_ranking(self, diagnosis_service):
        ws = diagnosis_service.get_kpi_workspace("debug_locations", mode="live")
        kinds = [p.kind for p in ws.panels]
        assert "debug_locations_panel" in kinds
        assert "debug_locations_table" in kinds

        panel = next(p for p in ws.panels if p.kind == "debug_locations_panel")
        table_panel = next(p for p in ws.panels if p.kind == "debug_locations_table")
        total = int(panel.meta.get("total_recommendations") or 0)
        assert total > 50, "expected more than legacy 50-row cap"
        assert len(table_panel.table) == total
        assert ws.summary.get("value") == total

        assert len(panel.table) >= 1
        top = panel.table[0]
        assert "rank" in top
        assert "evidence_bullets" in top
        assert "selection_rationale" in top
        assert "confidence_pct" in top

        full_row = table_panel.table[0]
        assert "rank" in full_row
        assert "pfa_priority" in full_row
        assert "die_occurrences" not in full_row
