"""
STIL ScanStructures parser.

Extracts the per-chain scan structure from the ``ScanStructures { ScanChain ... }``
block of a STIL file:

    ScanChain core_des__...__edt_block_channel1  {
        ScanLength 234;
        ScanInversion 0;
        ScanIn "ETH_TXCLK";
        ScanOut "ETH_RXD3";
        ScanMasterClock "ETH_RXCLK";
    }

This gives, for every chain:
    - scan_length            (number of scan cells / shift cycles)
    - scan_in / scan_out     (chain head/tail pins)
    - scan_master_clock
    - scan_inversion
    - cell_order             (ordered position -> cell-name mapping)

Real internal cell instance names are not enumerated in this EDT STIL, so the
ordered cell list is synthesised deterministically from the chain identity and
bit position (position 0 = bit nearest ScanOut, i.e. first bit shifted out).
This provides the position<->cell mapping required by SCD-FR-002.
"""

from __future__ import annotations

import re
from pathlib import Path

# ScanChain <name> {
SCANCHAIN_RE = re.compile(r"^\s*ScanChain\s+(\S+)\s*\{")
SCANLENGTH_RE = re.compile(r"^\s*ScanLength\s+(\d+)\s*;")
SCANIN_RE = re.compile(r'^\s*ScanIn\s+"?([^";]+)"?\s*;')
SCANOUT_RE = re.compile(r'^\s*ScanOut\s+"?([^";]+)"?\s*;')
SCANCLK_RE = re.compile(r'^\s*ScanMasterClock\s+"?([^";]+)"?\s*;')
SCANINV_RE = re.compile(r"^\s*ScanInversion\s+(\d+)\s*;")
CHANNEL_RE = re.compile(r"(channel\d+)", re.IGNORECASE)
CHAIN_INDEX_RE = re.compile(r"(?:channel|chain_?|ch_?)(\d+)", re.IGNORECASE)


def _short_chain(chain_id: str) -> str:
    m = CHANNEL_RE.search(chain_id or "")
    return m.group(1).lower() if m else (chain_id or "UNKNOWN")


def channel_index(name: str) -> int | None:
    """Canonical 1-based channel index from log/STIL/hierarchical names.

    Examples: ``channel05`` → 5, ``channel5`` → 5, ``chain_5`` → 5.
    """
    if not name:
        return None
    m = CHAIN_INDEX_RE.search(str(name))
    return int(m.group(1)) if m else None


def channel_log_variants(index: int) -> list[str]:
    """Log and STIL spellings for the same scan channel index."""
    return list(dict.fromkeys([
        f"channel{index:02d}",
        f"channel{index}",
        f"chain_{index}",
        f"chain{index}",
    ]))


def _chain_index_from_info(info: dict) -> int | None:
    for field in ("chain_id", "chain", "chain_name"):
        idx = channel_index(info.get(field, "") or "")
        if idx is not None:
            return idx
    return None


def _pick_chain_candidate(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    core = [c for c in candidates if "core_inst" in (c.get("chain_id") or "")]
    return core[0] if core else candidates[0]


def cell_name_at(chain_id: str, position: int) -> str:
    """Deterministic cell-instance name for a bit position within a chain.

    position 0 == bit nearest ScanOut (first shifted out).
    """
    num_match = re.search(r'(?:channel|chain_?)(\d+)', chain_id, re.IGNORECASE)
    if num_match:
        val = int(num_match.group(1))
        idx = val - 1 if "channel" in num_match.group(0).lower() else val
        return f"U_core/reg_c{idx}_ff[{position}]"
    return f"{chain_id}.sff_{position:03d}"


def build_cell_order(chain_id: str, scan_length: int) -> list[str]:
    """Ordered list of cell names, index = bit position from ScanOut."""
    return [cell_name_at(chain_id, i) for i in range(scan_length)]


def _infer_instance_type(chain_id: str) -> str:
    if "core_inst" in (chain_id or ""):
        return "core_inst"
    if "phy_inst" in (chain_id or ""):
        return "phy_inst"
    return "unknown"


def _infer_scan_enable(chain_id: str, scan_master_clock: str | None) -> str:
    cid = chain_id or ""
    if "edt_int_slow" in cid:
        mode = "SLOW"
    elif "edt_int_fast" in cid:
        mode = "FAST"
    else:
        mode = "STANDARD"
    clock = (scan_master_clock or "CLK").replace('"', "").strip()
    return f"SCAN_ENABLE_{clock}_{mode}"


def enrich_chain_topology(chain_info: dict, num_channels: int = 5) -> dict:
    """Enriches chain info with decompressor/compactor pins and hierarchical path (SCD-FR-003)."""
    chain_id = chain_info.get("chain_id", "")
    chain_short = chain_info.get("chain", "")
    clock = chain_info.get("scan_master_clock")
    chain_info["clock_domain"] = clock
    chain_info["instance_type"] = _infer_instance_type(chain_id)
    chain_info["scan_enable"] = _infer_scan_enable(chain_id, clock)

    num_match = re.search(r'(?:channel|chain_?|ch_?)(\d+)', chain_id, re.IGNORECASE)
    if not num_match:
        num_match = re.search(r'(?:channel|chain_?|ch_?)(\d+)', chain_short, re.IGNORECASE)

    if num_match:
        val = int(num_match.group(1))
        chain_info["chain_name"] = f"chain_{val}"
        idx = val - 1 if "channel" in num_match.group(0).lower() else val
        chain_info["decompressor_pin"] = f"edt_channels_in[{idx % num_channels}]"
        chain_info["compactor_pin"] = f"edt_channels_out[{idx % num_channels}]"
        chain_info["hierarchical_path"] = f"U_core/reg_c{idx}_ff"
    else:
        chain_info["chain_name"] = chain_short
        chain_info["decompressor_pin"] = "edt_channels_in[0]"
        chain_info["compactor_pin"] = "edt_channels_out[0]"
        chain_info["hierarchical_path"] = "U_core/unknown_ff"

    return chain_info


def parse_stil_scan_structures(path: str | Path) -> dict[str, dict]:
    """Parse the ScanStructures block; return {chain_short: chain_info}.

    chain_info keys: chain_id, chain, scan_length, scan_in, scan_out,
    scan_master_clock, scan_inversion, cell_order.
    """
    path = Path(path)
    chains: dict[str, dict] = {}

    in_scan_structures = False
    current: dict | None = None

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not in_scan_structures:
                if line.lstrip().startswith("ScanStructures"):
                    in_scan_structures = True
                continue

            # Inside ScanStructures.
            m = SCANCHAIN_RE.match(line)
            if m:
                chain_id = m.group(1)
                current = {
                    "chain_id": chain_id,
                    "chain": _short_chain(chain_id),
                    "scan_length": None,
                    "scan_in": None,
                    "scan_out": None,
                    "scan_master_clock": None,
                    "scan_inversion": None,
                }
                continue

            if current is not None:
                if (mm := SCANLENGTH_RE.match(line)):
                    current["scan_length"] = int(mm.group(1))
                elif (mm := SCANIN_RE.match(line)):
                    current["scan_in"] = mm.group(1).strip()
                elif (mm := SCANOUT_RE.match(line)):
                    current["scan_out"] = mm.group(1).strip()
                elif (mm := SCANCLK_RE.match(line)):
                    current["scan_master_clock"] = mm.group(1).strip()
                elif (mm := SCANINV_RE.match(line)):
                    current["scan_inversion"] = int(mm.group(1))
                elif line.strip() == "}":
                    # End of this ScanChain block. Key by FULL chain id, because
                    # core_inst and phy_inst chains share short names (channelN).
                    length = current["scan_length"] or 0
                    current["cell_order"] = build_cell_order(current["chain_id"], length)
                    chains[current["chain_id"]] = current
                    current = None

            # End of ScanStructures block (a closing brace at column 0).
            if in_scan_structures and current is None and line.rstrip() == "}":
                break

    # Dynamic post-parse enrichment pass
    unique_ins = {c["scan_in"] for c in chains.values() if c.get("scan_in")}
    num_ch = len(unique_ins) if unique_ins else 5
    for cid, c in chains.items():
        chains[cid] = enrich_chain_topology(c, num_channels=num_ch)

    return chains


def resolve_chain(chains: dict[str, dict], chain_id: str, chain_short: str) -> dict | None:
    """Resolve a chain by full id, normalized short name, or exact channel index."""
    if chain_id and chain_id in chains:
        return chains[chain_id]

    if chain_short:
        for info in chains.values():
            if (info.get("chain") or "").lower() == chain_short.lower():
                return info

    query_idx = channel_index(chain_short) or channel_index(chain_id)
    if query_idx is not None:
        variants = {v.lower() for v in channel_log_variants(query_idx)}
        candidates = [
            info for info in chains.values()
            if (info.get("chain") or "").lower() in variants
            or _chain_index_from_info(info) == query_idx
        ]
        picked = _pick_chain_candidate(candidates)
        if picked is not None:
            return picked

        # Legacy fallback only when exactly one off-by-one candidate exists.
        off_by_one = [
            info for info in chains.values()
            if _chain_index_from_info(info) in (query_idx - 1, query_idx + 1)
        ]
        if len(off_by_one) == 1:
            return off_by_one[0]

    return None


def chain_summary_rows(chains: dict[str, dict]) -> list[dict]:
    """Flatten chain info for display (without the big cell_order list)."""
    rows = []
    for info in chains.values():
        rows.append(
            {
                "chain": info["chain"],
                "scan_length": info["scan_length"],
                "scan_in": info["scan_in"],
                "scan_out": info["scan_out"],
                "scan_master_clock": info["scan_master_clock"],
                "scan_inversion": info["scan_inversion"],
            }
        )
    # Sort numerically by chain short name if possible
    def _num_key(r):
        val = "".join(c for c in r["chain"] if c.isdigit())
        return int(val) if val else 0
    rows.sort(key=_num_key)
    return rows


def parse_hardware_topology_md(path: str | Path) -> dict[str, dict]:
    """Parse the detailed scan chain map from the hardware_topology.md file."""
    path = Path(path)
    if not path.exists():
        return {}
    
    chains = {}
    in_table = False
    
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line_str = line.strip()
            if not in_table:
                # Find table header
                if line_str.startswith("| Chain Name") or (line_str.startswith("|") and "Hierarchical Instance" in line_str):
                    in_table = True
                continue
            
            # Inside the table
            if not line_str.startswith("|"):
                # Table ended (empty line or new header)
                if in_table and len(chains) > 0:
                    break
                continue
                
            # Skip separator line (e.g., | :--- | :---: |)
            if ":---" in line_str or "---:" in line_str:
                continue
                
            # Parse row
            parts = [p.strip() for p in line_str.split("|")[1:-1]]
            if len(parts) >= 5:
                chain_raw = parts[0].replace("**", "").replace("`", "").strip()
                cell_count = int(parts[1]) if parts[1].isdigit() else 234
                input_pin = parts[2].replace("`", "").strip()
                output_pin = parts[3].replace("`", "").strip()
                path_ref = parts[4].replace("`", "").strip()
                
                # Extract hierarchical path prefix
                path_prefix = path_ref
                if "[" in path_ref:
                    path_prefix = path_ref.split("[")[0]
                
                # Map chain_0 to channel1, chain_22 to channel23
                num_m = re.search(r'\d+', chain_raw)
                if num_m:
                    val = int(num_m.group(0))
                    chain_short = f"channel{val + 1}"
                else:
                    chain_short = chain_raw
                    
                cell_order = [f"{path_prefix}[{i}]" for i in range(cell_count)]
                
                # Create a structure matching STIL parser output format
                chains[chain_raw] = enrich_chain_topology({
                    "chain_id": chain_raw,
                    "chain": chain_short,
                    "scan_length": cell_count,
                    "scan_in": input_pin,
                    "scan_out": output_pin,
                    "scan_master_clock": "clk",
                    "scan_inversion": 0,
                    "cell_order": cell_order,
                    "chain_name": chain_raw,
                    "decompressor_pin": input_pin,
                    "compactor_pin": output_pin,
                    "hierarchical_path": path_prefix,
                })
    return chains


def find_topology_md_file(data_dir: Path) -> Path | None:
    """Locate the hardware topology markdown file in data_dir, supporting various spellings."""
    for filename in ["hadware_topology.md", "hardware_topology.md"]:
        p = data_dir / filename
        if p.exists():
            return p
    # Case-insensitive wildcard fallback
    if data_dir.exists():
        for p in data_dir.glob("*.md"):
            if "topology" in p.name.lower():
                return p
    return None


def resolve_active_stil_file(df: pd.DataFrame = None) -> Path | None:
    """Dynamically resolve the active STIL file based on the failures DataFrame pattern count or file timestamps."""
    from config import get_config
    cfg = get_config()
    stil_dir = cfg.project_root / "data" / "stil"
    if not stil_dir.exists():
        return None
    stil_files = list(stil_dir.glob("*.stil"))
    if not stil_files:
        return None
    
    # 1. Try matching based on total_patterns in the parsed dataframe
    if df is not None and not df.empty and "total_patterns" in df.columns:
        valid_pats = df["total_patterns"].dropna()
        if not valid_pats.empty:
            total_pat = int(valid_pats.iloc[0])
            pat_str = str(total_pat)
            matching = [f for f in stil_files if pat_str in f.name]
            if matching:
                matching.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                return matching[0]

    # 2. Fallback: return the most recently modified STIL file
    stil_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return stil_files[0]


