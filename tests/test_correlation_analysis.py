"""Tests for SCD-FR-005 correlation analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from correlation_analysis import (  # noqa: E402
    SCAN_LOAD_COLS,
    SPATIAL_COLS,
    build_correlation_rows,
    enrich_failures_with_topology,
)


def _sample_df() -> pd.DataFrame:
    rows = []
    for i in range(40):
        chain = "channel01" if i < 20 else "channel02"
        rows.append(
            {
                "chain": chain,
                "ir_drop_mv": 50 + (10 if chain == "channel01" else -5) + i * 0.1,
                "thermal_c": 80 + (5 if chain == "channel01" else -3),
                "setup_slack_ps": -20 + i * 0.05,
                "hold_slack_ps": -8,
                "ai_severity_score": 0.8,
                "shift_cycles": 200 + (20 if chain == "channel01" else 0),
                "capture_cycles": 10 + i % 3,
                "scan_fail_count": 2 if chain == "channel01" else 1,
                "transition_faults": 1,
                "test_time_ms": 500 + i,
                "die_row": 1 if i < 25 else 3,
                "die_col": 2 if i < 25 else 4,
                "wafer_x": 100.0 + i,
                "wafer_y": 200.0 - i * 0.5,
                "fail_type": "SCAN_SHIFT" if i % 2 == 0 else "CAPTURE",
                "die_label": "fail_die_1" if i < 25 else "fail_die_2",
                "failure_region": None,
                "root_cause_hint": "LOCAL" if chain == "channel01" else "EDGE_RING",
            }
        )
    return pd.DataFrame(rows)


def _sample_chain_map() -> dict:
    return {
        "core_des__channel1": {
            "chain": "channel01",
            "scan_length": 234,
            "scan_master_clock": "ETH_RXCLK",
            "clock_domain": "ETH_RXCLK",
            "decompressor_pin": "edt_channels_in[0]",
            "compactor_pin": "edt_channels_out[0]",
            "scan_in": "ETH_TXCLK",
            "scan_out": "ETH_RXD3",
            "instance_type": "core_inst",
        },
        "phy_des__channel2": {
            "chain": "channel02",
            "scan_length": 180,
            "scan_master_clock": "SYS_CLK",
            "clock_domain": "SYS_CLK",
            "decompressor_pin": "edt_channels_in[1]",
            "compactor_pin": "edt_channels_out[1]",
            "scan_in": "PHY_SI",
            "scan_out": "PHY_SO",
            "instance_type": "phy_inst",
        },
    }


class TestCorrelationAnalysis:
    def test_region_fallback_uses_die_label(self):
        correlations, overall, meta = build_correlation_rows(_sample_df())
        assert meta["region_field_used"] == "die_label"
        assert correlations
        ch1 = next(c for c in correlations if c["chain"] == "channel01")
        assert ch1["failure_region_percentages"]
        assert "fail_die_1" in ch1["failure_region_percentages"]

    def test_summary_strongest_correlation(self):
        correlations, _overall, meta = build_correlation_rows(_sample_df())
        summary = meta["summary"]
        assert summary["chain_count"] == 2
        assert summary["total_fail_records"] == 40
        assert summary["strongest_correlation"]["chain"] in {"channel01", "channel02"}
        assert summary["strongest_correlation"]["metric"] in meta["numerical_features"]

    def test_scan_load_and_spatial_features_in_meta(self):
        _correlations, _overall, meta = build_correlation_rows(_sample_df())
        for col in SCAN_LOAD_COLS:
            assert col in meta["scan_load_features"]
        for col in SPATIAL_COLS:
            assert col in meta["spatial_features"]
        assert "shift_cycles" in meta["numerical_features"]
        assert "scan_fail_count" in meta["numerical_features"]
        assert "die_row" in meta["spatial_features"]

    def test_spatial_correlations_subdict(self):
        correlations, _overall, _meta = build_correlation_rows(_sample_df())
        ch1 = next(c for c in correlations if c["chain"] == "channel01")
        assert "spatial_correlations" in ch1
        assert "die_row" in ch1["spatial_correlations"]
        assert "primary_spatial_driver" in ch1

    def test_topology_enrichment_and_profile(self):
        df = _sample_df()
        chain_map = _sample_chain_map()
        enriched = enrich_failures_with_topology(df, chain_map)
        assert "scan_length" in enriched.columns
        assert enriched["scan_length"].notna().any()

        correlations, _overall, meta = build_correlation_rows(df, chain_map=chain_map)
        assert meta["topology_available"] is True
        assert "scan_length" in meta["topology_fields"]
        ch1 = next(c for c in correlations if c["chain"] == "channel01")
        profile = ch1["topology_profile"]
        assert profile["scan_length"] == 234
        assert profile["clock_domain"] == "ETH_RXCLK"
        assert profile["instance_type"] == "core_inst"
        assert profile["compression_ratio"] is not None

    def test_topology_graceful_without_chain_map(self):
        correlations, _overall, meta = build_correlation_rows(_sample_df(), chain_map=None)
        assert meta["topology_available"] is False
        ch1 = next(c for c in correlations if c["chain"] == "channel01")
        assert ch1["topology_profile"] == {}

    def test_chain_averages_table(self):
        correlations, _overall, meta = build_correlation_rows(_sample_df())
        table = meta["chain_averages_table"]
        assert len(table) == 2
        assert "avg_ir_drop_mv" in table[0]
        assert "avg_shift_cycles" in table[0]
        assert table[0]["severity_level"] in {"High", "Medium", "Low", "N/A"}

    def test_overall_averages_populated(self):
        _correlations, overall, _meta = build_correlation_rows(_sample_df())
        assert overall["ir_drop_mv"] is not None
        assert overall["thermal_c"] is not None
        assert overall["shift_cycles"] is not None

    def test_correlation_based_failure_distributions(self):
        correlations, _overall, meta = build_correlation_rows(_sample_df())
        ch1 = next(c for c in correlations if c["chain"] == "channel01")
        assert "physical_timing_percentages" in ch1
        assert "correlation_driver_percentages" in ch1
        assert "correlation_group_percentages" in ch1
        assert "spatial_percentages" in ch1
        assert sum(ch1["physical_timing_percentages"].values()) == pytest.approx(100.0, abs=0.5)
        assert sum(ch1["correlation_driver_percentages"].values()) == pytest.approx(100.0, abs=0.5)
        assert "distribution_method" in meta
        assert "fail_type" not in str(meta.get("distribution_method", "")).lower()

    def test_chain_signature_profile_fields(self):
        correlations, overall, meta = build_correlation_rows(_sample_df())
        ch1 = next(c for c in correlations if c["chain"] == "channel01")
        assert ch1["metric_comparisons"]
        assert ch1["distinguishing_factors"]
        assert ch1["signature_bullets"]
        assert len(ch1["signature_bullets"]) >= 1
        assert meta.get("signature_method")
        assert meta.get("chain_signature_overview")
        assert meta.get("presentation") == "chain_signature_profile"
        assert meta.get("correlation_feature_count") == len(meta.get("numerical_features", [])) + (
            1 if meta.get("region_field_used") else 0
        )
        assert meta.get("chains_analyzed") == len(correlations)
        comp = ch1["metric_comparisons"][0]
        assert "label" in comp
        assert "chain_avg" in comp
        assert "overall_avg" in comp
        assert "pct_diff" in comp
