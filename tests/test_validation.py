"""test_validation.py — Unit tests for the validation module."""

from __future__ import annotations

import pandas as pd
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from validation import (
    validate_log_dataframe,
    validate_chain_map,
    data_quality_report,
    detect_duplicate_records,
)
from exceptions import ValidationError


class TestValidateLogDataframe:
    def test_valid_df_passes(self, minimal_failures_df):
        # Should not raise
        validate_log_dataframe(minimal_failures_df)

    def test_empty_df_raises(self):
        with pytest.raises(ValidationError, match="failure records"):
            validate_log_dataframe(pd.DataFrame())

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"lot_id": ["A"], "chain": ["ch1"]})
        with pytest.raises(ValidationError) as exc_info:
            validate_log_dataframe(df)
        assert exc_info.value.missing_columns  # should list missing cols

    def test_all_required_columns_present(self, minimal_failures_df):
        required = {"lot_id", "source_file", "chain_id", "chain", "fail_flop_id", "fail_type"}
        assert required.issubset(set(minimal_failures_df.columns))


class TestValidateChainMap:
    def test_valid_map_passes(self, minimal_chain_map):
        validate_chain_map(minimal_chain_map)

    def test_empty_map_raises(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_chain_map({})

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError):
            validate_chain_map([1, 2, 3])

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            validate_chain_map(None)


class TestDataQualityReport:
    def test_report_structure(self, minimal_failures_df):
        report = data_quality_report(minimal_failures_df)
        assert "total_records" in report
        assert "columns" in report
        assert "overall_completeness_pct" in report
        assert "duplicate_count" in report

    def test_total_records_correct(self, minimal_failures_df):
        report = data_quality_report(minimal_failures_df)
        assert report["total_records"] == 15

    def test_empty_df(self):
        report = data_quality_report(pd.DataFrame())
        assert report["total_records"] == 0
        assert report["overall_completeness_pct"] == 0.0

    def test_no_nulls_gives_100_pct(self, minimal_failures_df):
        # minimal_failures_df has no nulls
        report = data_quality_report(minimal_failures_df)
        assert report["overall_completeness_pct"] == 100.0

    def test_with_nulls(self):
        df = pd.DataFrame({"a": [1, None, 3], "b": [4, 5, 6]})
        report = data_quality_report(df)
        assert report["columns"]["a"]["null_count"] == 1
        assert report["columns"]["a"]["completeness_pct"] == pytest.approx(66.67, abs=0.1)


class TestDetectDuplicates:
    def test_no_duplicates(self, minimal_failures_df):
        dups = detect_duplicate_records(minimal_failures_df)
        assert dups.empty

    def test_detects_duplicates(self, minimal_failures_df):
        df_with_dups = pd.concat([minimal_failures_df, minimal_failures_df.iloc[:2]], ignore_index=True)
        dups = detect_duplicate_records(df_with_dups)
        assert len(dups) == 4  # 2 duplicated rows × 2 occurrences each
