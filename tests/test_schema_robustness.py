"""Tests for multi-client field aliases and schema normalization."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from correlation_analysis import build_correlation_rows, pick_categorical_field  # noqa: E402
from locate_cells import enrich_with_positions  # noqa: E402
from parser import parse_log_file, records_to_dataframe  # noqa: E402
from schema import canonicalize_field_name, normalize_failure_schema  # noqa: E402
from validation import validate_log_dataframe  # noqa: E402


ALIASED_LOG = """
TESTER_NAME        : ADVANTEST_V93000
LotId              : LOT_ALIAS
DieLabel           : die_A1
WaferX_MM          : 12.5
WaferY_MM          : -3.2

[PATTERN_ID : 000100]
ScanChainId        : core_des__edt_block_channel1
FAIL_FLOP          : FF_12
FAILURE_TYPE       : SCAN_SHIFT
STATUS             : FAIL
IR_DROP            : 42
"""


def test_canonicalize_field_aliases():
    assert canonicalize_field_name("DieLabel") == "die_label"
    assert canonicalize_field_name("WAFER_X_MM") == "wafer_x"
    assert canonicalize_field_name("FAIL_FLOP") == "fail_flop_id"
    assert canonicalize_field_name("LotId") == "lot_id"


def test_parse_log_with_alternate_headers():
    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False) as tmp:
        tmp.write(ALIASED_LOG)
        tmp_path = tmp.name

    try:
        meta, records = parse_log_file(tmp_path)
        assert meta["LOT_ID"] == "LOT_ALIAS"
        assert meta["DIE_LABEL"] == "die_A1"
        assert meta["WAFER_X"] == "12.5"
        assert len(records) == 1
        assert records[0]["SCAN_CHAIN_ID"] == "core_des__edt_block_channel1"
        assert records[0]["FAIL_FLOP_ID"] == "FF_12"
        assert records[0]["FAIL_TYPE"] == "SCAN_SHIFT"
        assert records[0]["IR_DROP_MV"] == "42"

        df = records_to_dataframe(meta, records)
        assert df.loc[0, "die_label"] == "die_A1"
        assert float(df.loc[0, "wafer_x"]) == pytest.approx(12.5)
        assert float(df.loc[0, "wafer_y"]) == pytest.approx(-3.2)
        assert df.loc[0, "ir_drop_mv"] == 42
    finally:
        Path(tmp_path).unlink()


def test_normalize_failure_schema_adds_missing_optional_columns():
    sparse = pd.DataFrame({
        "lot_id": ["L1"],
        "source_file": ["a.log"],
        "chain_id": ["core__channel1"],
        "chain": ["channel1"],
        "fail_flop_id": ["FF_1"],
        "fail_type": ["SCAN_SHIFT"],
    })
    out = normalize_failure_schema(sparse)
    assert "ir_drop_mv" in out.columns
    assert "die_label" in out.columns
    assert "failure_region" in out.columns
    assert pd.isna(out.loc[0, "ir_drop_mv"])


def test_validate_sparse_df_passes_with_warnings(caplog):
    import logging

    df = normalize_failure_schema(pd.DataFrame({
        "lot_id": ["L1"],
        "source_file": ["a.log"],
        "chain_id": ["core__channel1"],
        "chain": ["channel1"],
        "fail_flop_id": ["FF_1"],
        "fail_type": ["SCAN_SHIFT"],
    }))
    with caplog.at_level(logging.WARNING):
        validate_log_dataframe(df)
    assert "Optional client fields" in caplog.text


def test_locate_cells_without_shift_cycles(minimal_chain_map):
    df = normalize_failure_schema(pd.DataFrame({
        "lot_id": ["L1"],
        "source_file": ["a.log"],
        "chain_id": ["core__edt_block_channel1"],
        "chain": ["channel1"],
        "fail_flop_id": ["FF_10"],
        "fail_type": ["SCAN_SHIFT"],
    }))
    enriched = enrich_with_positions(df, minimal_chain_map)
    assert "chain_length" in enriched.columns
    assert enriched.loc[0, "chain_length"] == 234


def test_correlation_empty_categorical_columns():
    df = normalize_failure_schema(pd.DataFrame({
        "chain": ["channel1"] * 10,
        "ir_drop_mv": list(range(10, 20)),
        "thermal_c": [80] * 10,
        "setup_slack_ps": [-5] * 10,
        "hold_slack_ps": [2] * 10,
        "ai_severity_score": [0.5] * 10,
        "failure_region": [None] * 10,
        "die_label": [None] * 10,
        "defect_type": [None] * 10,
    }))
    assert pick_categorical_field(df, ["failure_region", "die_label", "defect_type"]) is None
    rows, _averages, meta = build_correlation_rows(df, chain_map={})
    assert isinstance(rows, list)
    assert meta.get("region_field_used") is None
