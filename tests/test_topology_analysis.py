"""Tests for SCD-FR-003 topology analysis module."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from stil_parser import parse_stil_scan_structures
from topology_analysis import (
    build_cell_connectivity,
    build_topology_analysis,
    compute_chain_balance,
    compute_shared_resources,
    infer_scan_enable,
    load_all_log_metadata,
    parse_log_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STIL_PATH = PROJECT_ROOT / "data" / "stil" / "Production_SCAN_stuck_at_2000pat.stil"
LOG_DIR = PROJECT_ROOT / "data" / "logs"


@pytest.fixture
def chain_map():
    if not STIL_PATH.exists():
        pytest.skip("STIL file not available")
    return parse_stil_scan_structures(STIL_PATH)


def test_parse_log_metadata_has_die_coords():
    logs = list(LOG_DIR.glob("LOT_*/*.log"))
    if not logs:
        pytest.skip("No log files")
    meta = parse_log_metadata(logs[0])
    assert "die_row" in meta or "DIE_ROW" in meta or meta.get("die_row")
    assert meta.get("source_file")


def test_load_all_log_metadata_count():
    records = load_all_log_metadata(LOG_DIR)
    assert len(records) == 90


def test_infer_scan_enable():
    se = infer_scan_enable(
        "core_des__edt_int_slow__edt_block_channel1",
        "ETH_RXCLK",
    )
    assert "SCAN_ENABLE" in se
    assert "SLOW" in se


def test_build_cell_connectivity():
    order = ["FF_A", "FF_B", "FF_C"]
    edges = build_cell_connectivity(order, "SI_PIN", "SO_PIN")
    assert edges[0]["from"] == "SI_PIN"
    assert edges[0]["to"] == "FF_A"
    assert edges[-1]["to"] == "SO_PIN"
    assert len(edges) == 4  # SI->A, A->B, B->C, C->SO


def test_compute_chain_balance_balanced():
    bal = compute_chain_balance([234, 234, 234])
    assert bal["is_balanced"] is True
    assert bal["imbalance_pct"] == 0.0


def test_compute_chain_balance_imbalanced():
    bal = compute_chain_balance([100, 200, 300])
    assert bal["is_balanced"] is False
    assert bal["max_length"] == 300


def test_compute_shared_resources(chain_map):
    shared = compute_shared_resources(chain_map)
    assert "shared_clocks" in shared
    assert "shared_scan_enable" in shared
    assert "tap_signals" in shared


def test_build_topology_analysis_complete(chain_map):
    topo = build_topology_analysis(chain_map, failures=pd.DataFrame(), log_dir=LOG_DIR)
    assert topo["status"] == "satisfied"
    assert topo["number_of_scan_chains"] == 23
    assert len(topo["chains"]) == 23

    chain = topo["chains"][0]
    assert "scan_chain_id" in chain
    assert "scan_cell_order" in chain
    assert "scan_cell_connectivity" in chain
    assert "scan_enable_se" in chain
    assert "clock_domain" in chain
    assert "physical_locations" in chain
    assert "compression_association" in chain
    assert len(chain["scan_cell_names"]) == 234

    graph = topo["connectivity_graph"]
    assert graph["node_count"] > 0
    assert graph["edge_count"] > 0

    assert topo["summary"]["logs_analyzed"] == 90


def test_build_topology_analysis_with_failures(chain_map):
    logs = list(LOG_DIR.glob("LOT_1_Center/*.log"))[:2]
    if not logs:
        pytest.skip("No logs")
    from parser import parse_log_to_dataframe

    frames = [parse_log_to_dataframe(p) for p in logs]
    df = pd.concat(frames, ignore_index=True)
    topo = build_topology_analysis(chain_map, failures=df, log_dir=LOG_DIR)
    assert topo["summary"]["failure_records_analyzed"] == len(df)
