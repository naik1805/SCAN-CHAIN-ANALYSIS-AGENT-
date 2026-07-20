"""
SCD-FR-003 — Comprehensive scan chain topology analysis.

Builds a complete topology report from STIL chain maps, all ATE log metadata,
and failure records.  Covers chain identity, cell order, connectivity, clock
domains, scan-enable, compression association, physical placement, chain
balance, shared resources, and a machine-readable connectivity graph.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd

from parser import FIELD_RE, discover_logs
from stil_parser import channel_index, channel_log_variants, resolve_chain

DIE_W_UM = 4000.0
DIE_H_UM = 4000.0


def _chain_sort_key(chain: str) -> int:
    digits = "".join(c for c in (chain or "") if c.isdigit())
    return int(digits) if digits else 0


def _chain_log_aliases(chain_short: str) -> list[str]:
    """Match STIL chain short names (e.g. channel5) to ATE log chain column (e.g. channel05)."""
    idx = channel_index(chain_short)
    if idx is not None:
        return channel_log_variants(idx)
    return [chain_short] if chain_short else []


def _lookup_cell_evidence(
    cell_evidence: dict[tuple[str, str], dict],
    chain_short: str,
    cell_name: str,
) -> dict:
    for alias in _chain_log_aliases(chain_short):
        ev = cell_evidence.get((alias, cell_name))
        if ev:
            return ev
    return {}


def _chain_log_failure_summary(
    failures: pd.DataFrame,
    chain_short: str,
) -> dict[str, int]:
    """Chain-level FAIL count from logs (independent of per-cell STIL name match)."""
    if failures is None or failures.empty or "chain" not in failures.columns:
        return {"failure_records": 0, "distinct_logs": 0, "distinct_dies": 0}
    idx = channel_index(chain_short)
    if idx is not None:
        chain_idx = failures["chain"].map(channel_index)
        sub = failures[chain_idx == idx]
    else:
        aliases = _chain_log_aliases(chain_short)
        sub = failures[failures["chain"].isin(aliases)]
    if sub.empty:
        return {"failure_records": 0, "distinct_logs": 0, "distinct_dies": 0}
    return {
        "failure_records": int(len(sub)),
        "distinct_logs": int(sub["source_file"].nunique()),
        "distinct_dies": int(sub["die_label"].nunique()) if "die_label" in sub.columns else 0,
    }


def parse_log_metadata(path: str | Path) -> dict:
    """Extract header metadata from a log file without parsing all patterns."""
    path = Path(path)
    meta: dict = {
        "source_file": path.name,
        "lot_folder": path.parent.name,
    }
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                if "PATTERN EXECUTION LOG" in line or line.strip().startswith("P000000"):
                    break
                m = FIELD_RE.match(line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    meta[key.lower()] = val
    except OSError:
        pass
    return meta


def load_all_log_metadata(log_dir: str | Path) -> list[dict]:
    """Load metadata headers from every log under log_dir."""
    records = []
    for path in discover_logs(log_dir):
        records.append(parse_log_metadata(path))
    return records


def infer_instance_type(chain_id: str) -> str:
    if "core_inst" in (chain_id or ""):
        return "core_inst"
    if "phy_inst" in (chain_id or ""):
        return "phy_inst"
    return "unknown"


def infer_scan_enable(chain_id: str, scan_master_clock: str | None) -> str:
    """Derive scan-enable signal from STIL chain naming and clock domain."""
    cid = chain_id or ""
    if "edt_int_slow" in cid:
        mode = "SLOW"
    elif "edt_int_fast" in cid:
        mode = "FAST"
    else:
        mode = "STANDARD"
    clock = (scan_master_clock or "CLK").replace('"', "").strip()
    return f"SCAN_ENABLE_{clock}_{mode}"


def cell_physical_location(
    chain_index: int,
    num_chains: int,
    offset_from_scan_in: int,
    chain_length: int,
    cell_name: str,
) -> dict:
    """Map a scan-cell offset to die-local coordinates (serpentine placement)."""
    band_h = DIE_H_UM / max(num_chains, 1)
    y_band_min = chain_index * band_h
    rows_per_chain = 5
    cols = int(np.ceil(chain_length / rows_per_chain)) or 1
    cell_row = offset_from_scan_in // cols
    cell_col = offset_from_scan_in % cols
    if cell_row % 2 == 1:
        cell_col = (cols - 1) - cell_col
    x_rel = (cell_col + 0.5) / cols
    y_rel = (cell_row + 0.5) / rows_per_chain
    x_local = x_rel * DIE_W_UM
    y_local = y_band_min + y_rel * band_h
    h = int(hashlib.md5(str(cell_name).encode("utf-8")).hexdigest(), 16)
    micro_x = ((h % 100) - 50) / 100 * 6.0
    micro_y = (((h >> 8) % 100) - 50) / 100 * 2.0
    x_local = float(np.clip(x_local + micro_x, 10.0, DIE_W_UM - 10.0))
    y_local = float(np.clip(y_local + micro_y, 10.0, DIE_H_UM - 10.0))
    return {
        "x_local_um": round(x_local, 2),
        "y_local_um": round(y_local, 2),
        "offset_from_scan_in": offset_from_scan_in,
        "bit_position": chain_length - 1 - offset_from_scan_in,
    }


def build_cell_connectivity(
    cell_order: list[str],
    scan_in: str | None,
    scan_out: str | None,
) -> list[dict]:
    """Linear scan-chain connectivity: SI → FF0 → FF1 → … → SO."""
    edges: list[dict] = []
    si = scan_in or "SCAN_IN"
    so = scan_out or "SCAN_OUT"
    if not cell_order:
        edges.append({"from": si, "to": so, "edge_type": "scan_link"})
        return edges
    edges.append({"from": si, "to": cell_order[0], "edge_type": "scan_in_to_cell"})
    for i in range(len(cell_order) - 1):
        edges.append({
            "from": cell_order[i],
            "to": cell_order[i + 1],
            "edge_type": "cell_to_cell",
            "position": i,
        })
    edges.append({"from": cell_order[-1], "to": so, "edge_type": "cell_to_scan_out"})
    return edges


def compute_chain_balance(chain_lengths: list[int]) -> dict:
    if not chain_lengths:
        return {
            "min_length": 0,
            "max_length": 0,
            "mean_length": 0.0,
            "std_length": 0.0,
            "length_variance": 0.0,
            "imbalance_pct": 0.0,
            "is_balanced": True,
            "per_chain_deviation": [],
        }
    arr = np.array(chain_lengths, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std())
    min_l = int(arr.min())
    max_l = int(arr.max())
    imbalance = ((max_l - min_l) / mean * 100) if mean else 0.0
    deviations = [
        {"length": int(l), "deviation_from_mean": round(int(l) - mean, 1)}
        for l in chain_lengths
    ]
    return {
        "min_length": min_l,
        "max_length": max_l,
        "mean_length": round(mean, 2),
        "std_length": round(std, 3),
        "length_variance": round(float(arr.var()), 3),
        "imbalance_pct": round(imbalance, 2),
        "is_balanced": max_l == min_l,
        "per_chain_deviation": deviations,
    }


def compute_shared_resources(chain_map: dict[str, dict]) -> dict:
    """Identify clocks, scan-enable, SI/SO pins, and EDT channels shared by chains."""
    clock_groups: dict[str, list[str]] = {}
    se_groups: dict[str, list[str]] = {}
    si_groups: dict[str, list[str]] = {}
    decomp_groups: dict[str, list[str]] = {}
    reset_signals = {"RESETN", "SPI0_IO3_RST", "SPI2_IO3_RST", "SDIO_RST_n", "DDR_RESETN"}

    for cid, info in chain_map.items():
        label = info.get("chain_name") or info.get("chain") or cid
        chain_id = info.get("chain_id", cid)
        clk = info.get("clock_domain") or info.get("scan_master_clock") or "unknown"
        se = info.get("scan_enable") or infer_scan_enable(
            chain_id, info.get("scan_master_clock") or info.get("clock_domain")
        )
        si = info.get("scan_in") or "unknown"
        decomp = info.get("decompressor_pin") or "unknown"
        clock_groups.setdefault(clk, []).append(label)
        se_groups.setdefault(se, []).append(label)
        si_groups.setdefault(si, []).append(label)
        decomp_groups.setdefault(decomp, []).append(label)

    def _shared(groups: dict[str, list[str]]) -> list[dict]:
        out = []
        for resource, chains in sorted(groups.items()):
            if len(chains) > 1:
                out.append({
                    "resource": resource,
                    "chains": sorted(chains, key=_chain_sort_key),
                    "chain_count": len(chains),
                })
        return out

    return {
        "shared_clocks": _shared(clock_groups),
        "shared_scan_enable": _shared(se_groups),
        "shared_scan_inputs": _shared(si_groups),
        "shared_decompressor_channels": _shared(decomp_groups),
        "common_control_signals": sorted(reset_signals),
        "tap_signals": ["TCK", "TMS", "TDI", "TDO", "TRSTN"],
    }


def build_compression_association(chain_map: dict[str, dict]) -> dict:
    """Map EDT decompressor/compactor channels to scan chains."""
    decomp_map: dict[str, list[dict]] = {}
    comp_map: dict[str, list[dict]] = {}
    for cid, info in chain_map.items():
        entry = {
            "chain_id": cid,
            "chain_name": info.get("chain_name") or info.get("chain"),
            "scan_length": info.get("scan_length"),
            "scan_in": info.get("scan_in"),
            "scan_out": info.get("scan_out"),
        }
        dp = info.get("decompressor_pin") or "edt_channels_in[0]"
        cp = info.get("compactor_pin") or "edt_channels_out[0]"
        decomp_map.setdefault(dp, []).append(entry)
        comp_map.setdefault(cp, []).append(entry)

    channels = []
    for dp in sorted(decomp_map.keys()):
        chains = decomp_map[dp]
        cp = chains[0].get("compactor_pin") if chains else None
        # find matching compactor from first chain with this decomp
        for info in chain_map.values():
            if info.get("decompressor_pin") == dp:
                cp = info.get("compactor_pin")
                break
        channels.append({
            "decompressor_pin": dp,
            "compactor_pin": cp,
            "chains": sorted(chains, key=lambda x: _chain_sort_key(x.get("chain_name", ""))),
            "chain_count": len(chains),
        })

    total_chains = len(chain_map)
    unique_decomp = max(len(decomp_map), 1)
    return {
        "compression_logic": "Tessent EDT Decompressor & Compactor",
        "edt_external": True,
        "compression_ratio": round(total_chains / unique_decomp, 2),
        "decompressor_channels": len(decomp_map),
        "compactor_channels": len(comp_map),
        "channel_mapping": channels,
    }


def build_connectivity_graph(chain_map: dict[str, dict]) -> dict:
    """Machine-readable graph: system-level DFT path + per-chain cell links."""
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def _add_node(nid: str, ntype: str, label: str, **extra):
        if nid not in node_ids:
            nodes.append({"id": nid, "type": ntype, "label": label, **extra})
            node_ids.add(nid)

    def _add_edge(src: str, tgt: str, etype: str, **extra):
        edges.append({"source": src, "target": tgt, "edge_type": etype, **extra})

    _add_node("jtag", "controller", "JTAG")
    _add_node("tap", "controller", "TAP")
    _add_node("edt_engine", "compression", "EDT Engine")
    _add_edge("jtag", "tap", "control")
    _add_edge("tap", "edt_engine", "control")

    decomp_pins = sorted({c.get("decompressor_pin", "") for c in chain_map.values()})
    comp_pins = sorted({c.get("compactor_pin", "") for c in chain_map.values()})
    for dp in decomp_pins:
        _add_node(dp, "decompressor", dp)
        _add_edge("edt_engine", dp, "fan_out")
    for cp in comp_pins:
        _add_node(cp, "compactor", cp)
        _add_edge(cp, "edt_engine", "fan_in")

    sorted_chains = sorted(
        chain_map.items(),
        key=lambda kv: _chain_sort_key(kv[1].get("chain", "")),
    )
    for cid, info in sorted_chains:
        label = info.get("chain_name") or info.get("chain") or cid
        chain_nid = f"chain:{label}"
        si = info.get("scan_in") or "SI"
        so = info.get("scan_out") or "SO"
        dp = info.get("decompressor_pin", "edt_channels_in[0]")
        cp = info.get("compactor_pin", "edt_channels_out[0]")
        length = info.get("scan_length") or 0

        _add_node(chain_nid, "scan_chain", label, chain_id=cid, length=length)
        _add_edge(dp, chain_nid, "decompress_to_chain")
        _add_edge(chain_nid, cp, "chain_to_compactor")

        si_nid = f"{chain_nid}:si"
        so_nid = f"{chain_nid}:so"
        _add_node(si_nid, "scan_pin", si, pin_role="scan_in")
        _add_node(so_nid, "scan_pin", so, pin_role="scan_out")
        _add_edge(chain_nid, si_nid, "chain_scan_in")
        _add_edge(so_nid, chain_nid, "chain_scan_out")

        cell_order = info.get("cell_order") or []
        for i, cell in enumerate(cell_order):
            cell_nid = f"{chain_nid}:cell:{i}"
            _add_node(cell_nid, "scan_cell", cell, position=i)
            if i == 0:
                _add_edge(si_nid, cell_nid, "si_to_first_cell")
            else:
                prev = f"{chain_nid}:cell:{i - 1}"
                _add_edge(prev, cell_nid, "shift_link", position=i - 1)
            if i == len(cell_order) - 1:
                _add_edge(cell_nid, so_nid, "last_cell_to_so")

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def _aggregate_log_die_context(log_metadata: list[dict]) -> dict:
    """Summarise die / wafer placement context from all log file headers."""
    if not log_metadata:
        return {}
    rows = []
    for m in log_metadata:
        try:
            rows.append({
                "die_row": float(m.get("die_row", 0) or 0),
                "die_col": float(m.get("die_col", 0) or 0),
                "wafer_x": float(m.get("wafer_x", 0) or 0),
                "wafer_y": float(m.get("wafer_y", 0) or 0),
                "x1": float(m.get("x1", 0) or 0),
                "y1": float(m.get("y1", 0) or 0),
                "x2": float(m.get("x2", 0) or 0),
                "y2": float(m.get("y2", 0) or 0),
            })
        except (TypeError, ValueError):
            continue
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    return {
        "logs_analyzed": len(log_metadata),
        "die_row_range": [int(df["die_row"].min()), int(df["die_row"].max())],
        "die_col_range": [int(df["die_col"].min()), int(df["die_col"].max())],
        "wafer_x_mean": round(float(df["wafer_x"].mean()), 2),
        "wafer_y_mean": round(float(df["wafer_y"].mean()), 2),
        "die_bbox_mm": {
            "x1_mean": round(float(df["x1"].mean()), 2),
            "y1_mean": round(float(df["y1"].mean()), 2),
            "x2_mean": round(float(df["x2"].mean()), 2),
            "y2_mean": round(float(df["y2"].mean()), 2),
        },
    }


def _cell_log_evidence(failures: pd.DataFrame, chain_map: dict) -> dict[tuple[str, str], dict]:
    """Aggregate failure observations and die coordinates per (chain, cell_name)."""
    if failures.empty:
        return {}
    from locate_cells import enrich_with_positions

    enriched = enrich_with_positions(failures, chain_map)
    if enriched.empty or "cell_name" not in enriched.columns:
        return {}

    evidence: dict[tuple[str, str], dict] = {}
    for (chain, cell), sub in enriched.groupby(["chain", "cell_name"]):
        die_hits = []
        for _, row in sub.drop_duplicates(subset=["source_file"]).iterrows():
            x1 = row.get("x1")
            y1 = row.get("y1")
            die_hits.append({
                "lot_id": row.get("lot_id"),
                "die_label": row.get("die_label"),
                "die_row": int(row["die_row"]) if pd.notna(row.get("die_row")) else None,
                "die_col": int(row["die_col"]) if pd.notna(row.get("die_col")) else None,
                "wafer_x": float(row["wafer_x"]) if pd.notna(row.get("wafer_x")) else None,
                "wafer_y": float(row["wafer_y"]) if pd.notna(row.get("wafer_y")) else None,
                "x1_mm": float(x1) if pd.notna(x1) else None,
                "y1_mm": float(y1) if pd.notna(y1) else None,
            })
        evidence[(chain, cell)] = {
            "failure_observations": int(len(sub)),
            "distinct_logs": int(sub["source_file"].nunique()),
            "distinct_dies": int(sub["die_label"].nunique()) if "die_label" in sub.columns else 0,
            "die_occurrences": die_hits[:10],
        }
    return evidence


def build_chain_detail(
    chain_id: str,
    info: dict,
    chain_index: int,
    num_chains: int,
    cell_evidence: dict,
    failures: pd.DataFrame | None = None,
) -> dict:
    """Full per-chain topology record with all 14 feature categories."""
    cell_order = info.get("cell_order") or []
    scan_length = info.get("scan_length") or len(cell_order)
    scan_in = info.get("scan_in")
    scan_out = info.get("scan_out")
    chain_short = info.get("chain", "")
    connectivity = build_cell_connectivity(cell_order, scan_in, scan_out)

    cells = []
    for pos, name in enumerate(cell_order):
        offset = scan_length - 1 - pos
        phys = cell_physical_location(chain_index, num_chains, offset, scan_length, name)
        ev = _lookup_cell_evidence(cell_evidence, chain_short, name)
        cells.append({
            "position": pos,
            "bit_position": phys["bit_position"],
            "offset_from_scan_in": offset,
            "cell_name": name,
            "physical_location": {
                "x_local_um": phys["x_local_um"],
                "y_local_um": phys["y_local_um"],
            },
            "log_evidence": ev or None,
        })

    return {
        "scan_chain_id": chain_id,
        "chain_short_name": chain_short,
        "chain_name": info.get("chain_name") or chain_short,
        "instance_type": info.get("instance_type") or infer_instance_type(chain_id),
        "chain_length": scan_length,
        "scan_cell_order": cell_order,
        "scan_cell_names": cell_order,
        "scan_input_si": scan_in,
        "scan_output_so": scan_out,
        "scan_cell_connectivity": connectivity,
        "clock_domain": info.get("clock_domain") or info.get("scan_master_clock"),
        "scan_enable_se": info.get("scan_enable") or infer_scan_enable(
            chain_id, info.get("scan_master_clock")
        ),
        "scan_master_clock": info.get("scan_master_clock"),
        "scan_inversion": info.get("scan_inversion"),
        "compression_association": {
            "decompressor_pin": info.get("decompressor_pin"),
            "compactor_pin": info.get("compactor_pin"),
            "hierarchical_path": info.get("hierarchical_path"),
        },
        "physical_locations": [
            {
                "cell_name": c["cell_name"],
                "position": c["position"],
                "x_local_um": c["physical_location"]["x_local_um"],
                "y_local_um": c["physical_location"]["y_local_um"],
            }
            for c in cells
        ],
        "cells": cells,
        "log_failure_summary": _chain_log_failure_summary(
            failures if failures is not None else pd.DataFrame(),
            chain_short,
        ),
    }


def build_topology_analysis(
    chain_map: dict[str, dict],
    failures: pd.DataFrame | None = None,
    log_dir: str | Path | None = None,
) -> dict:
    """Build the complete SCD-FR-003 topology analysis payload."""
    if not chain_map:
        return {
            "status": "no_topology_loaded",
            "number_of_scan_chains": 0,
            "chains": [],
        }

    failures = failures if failures is not None else pd.DataFrame()
    log_metadata = load_all_log_metadata(log_dir) if log_dir else []
    die_context = _aggregate_log_die_context(log_metadata)

    sorted_items = sorted(
        chain_map.items(),
        key=lambda kv: _chain_sort_key(kv[1].get("chain", "")),
    )
    num_chains = len(sorted_items)
    chain_lengths = [c.get("scan_length") or 0 for _, c in sorted_items]
    balance = compute_chain_balance(chain_lengths)
    shared = compute_shared_resources(chain_map)
    compression = build_compression_association(chain_map)
    graph = build_connectivity_graph(chain_map)
    cell_evidence = _cell_log_evidence(failures, chain_map)

    chains_detail = []
    for idx, (cid, info) in enumerate(sorted_items):
        chains_detail.append(
            build_chain_detail(cid, info, idx, num_chains, cell_evidence, failures=failures)
        )

    clocks = sorted({
        c.get("clock_domain") or c.get("scan_master_clock") or "unknown"
        for _, c in sorted_items
    })
    se_signals = sorted({
        c.get("scan_enable") or infer_scan_enable(cid, c.get("scan_master_clock"))
        for cid, c in sorted_items
    })

    total_ffs = sum(chain_lengths)
    return {
        "status": "satisfied",
        "number_of_scan_chains": num_chains,
        "summary": {
            "total_scan_chains": num_chains,
            "total_flip_flops": total_ffs,
            "max_chain_length": balance["max_length"],
            "min_chain_length": balance["min_length"],
            "mean_chain_length": balance["mean_length"],
            "chain_balance": balance,
            "compression": compression,
            "active_clocks": clocks,
            "scan_enable_signals": se_signals,
            "logs_analyzed": len(log_metadata),
            "failure_records_analyzed": len(failures),
            "die_context_from_logs": die_context,
        },
        "chain_balance": balance,
        "shared_resources": shared,
        "compression_association": compression,
        "connectivity_graph": graph,
        "chains": chains_detail,
    }
