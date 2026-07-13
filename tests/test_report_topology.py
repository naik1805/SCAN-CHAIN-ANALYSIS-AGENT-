"""Tests for FR-008 report topology section (Section 3)."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from diagnosis_context import build_diagnosis_bundle, render_topology_section_html
from parser import parse_log_to_dataframe
from report_generator import generate_html_report
from stil_parser import parse_stil_scan_structures

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "data" / "logs"
STIL_DIR = PROJECT_ROOT / "data" / "stil"


@pytest.fixture
def chain_map():
    stil_files = sorted(STIL_DIR.glob("*.stil"))
    if not stil_files:
        pytest.skip("No STIL files available")
    return parse_stil_scan_structures(stil_files[0])


@pytest.fixture
def failures_df():
    logs = list(LOG_DIR.glob("LOT_1_Center/*.log"))[:2]
    if not logs:
        pytest.skip("No logs available")
    frames = [parse_log_to_dataframe(p) for p in logs]
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        pytest.skip("Parsed logs contained no failures")
    return df


def test_topology_section_includes_full_analysis(chain_map, failures_df):
    bundle = build_diagnosis_bundle(
        failures_df, chain_map, log_dir=LOG_DIR, project_root=PROJECT_ROOT
    )
    html = render_topology_section_html(
        bundle["topology"],
        failing_chains=bundle["failing_chains"],
        failing_chain_ids=bundle["failing_chain_ids"],
    )
    assert "3.1 Topology Summary" in html
    assert "3.2 Chain Balance Analysis" in html
    assert "3.3 Shared Resources" in html
    assert "3.4 EDT Compression Association" in html
    assert "3.6 Complete Scan Chain Registry" in html
    assert "3.7 Cell Order" in html
    assert bundle["topology"]["number_of_scan_chains"] == 23


def test_html_report_section3_uses_topology_bundle(chain_map, failures_df, tmp_path):
    out = tmp_path / "report.html"
    generate_html_report(
        failures_df, chain_map, out,
        log_dir=LOG_DIR, project_root=PROJECT_ROOT,
    )
    content = out.read_text(encoding="utf-8")
    assert "3. Scan Chain Topology Map (FR-003)" in content
    assert "3.1 Topology Summary" in content
    assert "Complete Scan Chain Registry" in content
    assert "Shared Decompressor Channels" in content
    assert "EDT Compression" in content
