"""Tests for canonical channel index resolution (log channel05 ↔ STIL channel5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from locate_cells import enrich_with_positions
from stil_parser import channel_index, channel_log_variants, resolve_chain
from topology_analysis import build_topology_analysis

PROJECT_ROOT = Path(__file__).parent.parent


def _chain_map_channel4_and_5() -> dict[str, dict]:
    return {
        "core_des__edt_int_slow__edt_MY_DES_edt_tessent_edt_core_inst__edt_block_channel4": {
            "chain_id": "core_des__edt_int_slow__edt_MY_DES_edt_tessent_edt_core_inst__edt_block_channel4",
            "chain": "channel4",
            "chain_name": "chain_4",
            "scan_length": 234,
            "scan_in": "SI4",
            "scan_out": "SO4",
            "cell_order": [f"U_core/reg_c3_ff[{i}]" for i in range(234)],
            "hierarchical_path": "U_core/reg_c3_ff",
        },
        "core_des__edt_int_slow__edt_MY_DES_edt_tessent_edt_core_inst__edt_block_channel5": {
            "chain_id": "core_des__edt_int_slow__edt_MY_DES_edt_tessent_edt_core_inst__edt_block_channel5",
            "chain": "channel5",
            "chain_name": "chain_5",
            "scan_length": 234,
            "scan_in": "SI5",
            "scan_out": "SO5",
            "cell_order": [f"U_core/reg_c4_ff[{i}]" for i in range(234)],
            "hierarchical_path": "U_core/reg_c4_ff",
        },
    }


class TestChannelIndex:
    def test_channel_index_zero_padded_log(self):
        assert channel_index("channel05") == 5

    def test_channel_index_stil_short(self):
        assert channel_index("channel5") == 5

    def test_channel_index_chain_name(self):
        assert channel_index("chain_5") == 5

    def test_channel_log_variants(self):
        assert "channel05" in channel_log_variants(5)
        assert "channel5" in channel_log_variants(5)


class TestResolveChain:
    def test_channel05_maps_to_channel5_not_channel4(self):
        chains = _chain_map_channel4_and_5()
        info = resolve_chain(chains, "channel05", "channel05")
        assert info is not None
        assert info["chain"] == "channel5"
        assert info["chain_name"] == "chain_5"

    def test_enrich_uses_chain5_cell_names(self):
        chains = _chain_map_channel4_and_5()
        df = pd.DataFrame([{
            "chain_id": "channel05",
            "chain": "channel05",
            "fail_flop_id": "FF_13",
            "shift_cycles": 234,
        }])
        enriched = enrich_with_positions(df, chains)
        assert enriched["cell_name"].iloc[0] == "U_core/reg_c4_ff[12]"


@pytest.mark.integration
class TestResolveChainLive:
    def test_live_channel05_topology_cell_evidence(self):
        sys.path.insert(0, str(PROJECT_ROOT / "api"))
        from adapters.data_loader import load_failures, load_chain_map
        from adapters.paths import LOG_DIR

        failures, _ = load_failures(max_per_lot=None)
        chain_map, _ = load_chain_map()
        if not chain_map:
            pytest.skip("No chain map")

        topo = build_topology_analysis(chain_map, failures=failures, log_dir=LOG_DIR)
        ch5 = next(
            c for c in topo["chains"]
            if c.get("chain_name") == "chain_5" and c.get("instance_type") == "core_inst"
        )
        with_evidence = sum(1 for cell in ch5["cells"] if cell.get("log_evidence"))
        assert with_evidence > 0, "chain_5 should have per-cell log evidence after index fix"
