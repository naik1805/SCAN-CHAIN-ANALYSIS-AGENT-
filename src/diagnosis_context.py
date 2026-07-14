"""
Central diagnosis bundle for reports and exports.

All phase analyses that feed FR-008 should be assembled here so UI phases,
JSON exports, and HTML reports stay in sync when analysis logic changes.
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd

from topology_analysis import build_topology_analysis

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = APP_DIR.parent
DEFAULT_LOG_DIR = DEFAULT_PROJECT_ROOT / "data" / "logs"


def _esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def resolve_log_dir(log_dir: str | Path | None = None, project_root: Path | None = None) -> Path:
    if log_dir is not None:
        return Path(log_dir)
    root = project_root or DEFAULT_PROJECT_ROOT
    return root / "data" / "logs"


def build_diagnosis_bundle(
    df: pd.DataFrame,
    chain_map: dict,
    log_dir: str | Path | None = None,
    project_root: Path | None = None,
) -> dict:
    """Build all shared analysis artifacts used by Phase 7 / FR-008."""
    resolved_log_dir = resolve_log_dir(log_dir, project_root)
    topology = build_topology_analysis(
        chain_map,
        failures=df,
        log_dir=resolved_log_dir,
    )
    failing_chains = set()
    failing_chain_ids = set()
    if not df.empty:
        if "chain" in df.columns:
            failing_chains = set(df["chain"].dropna().astype(str).unique())
        if "chain_id" in df.columns:
            failing_chain_ids = set(df["chain_id"].dropna().astype(str).unique())

    return {
        "topology": topology,
        "log_dir": resolved_log_dir,
        "failing_chains": failing_chains,
        "failing_chain_ids": failing_chain_ids,
        "failure_record_count": len(df),
    }


def _shared_resource_table(items: list[dict], resource_col: str) -> str:
    if not items:
        return "<p>No shared resources detected (each chain uses a unique resource).</p>"
    rows = []
    for item in items:
        chains = ", ".join(_esc(c) for c in item.get("chains", []))
        rows.append(
            f"<tr><td class='mono'>{_esc(item.get(resource_col))}</td>"
            f"<td class='mono'>{item.get('chain_count', 0)}</td>"
            f"<td>{chains}</td></tr>"
        )
    return f"""
    <table>
        <thead>
            <tr>
                <th>{_esc(resource_col.replace('_', ' ').title())}</th>
                <th>Chain Count</th>
                <th>Chains</th>
            </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
    </table>
    """


def _compression_channel_table(channels: list[dict]) -> str:
    if not channels:
        return "<p>No EDT channel mapping available.</p>"
    rows = []
    for ch in channels:
        chain_labels = ", ".join(
            _esc(c.get("chain_name") or c.get("chain_id", ""))
            for c in ch.get("chains", [])
        )
        rows.append(
            f"<tr>"
            f"<td class='mono'>{_esc(ch.get('decompressor_pin'))}</td>"
            f"<td class='mono'>{_esc(ch.get('compactor_pin'))}</td>"
            f"<td class='mono'>{ch.get('chain_count', 0)}</td>"
            f"<td>{chain_labels}</td>"
            f"</tr>"
        )
    return f"""
    <table>
        <thead>
            <tr>
                <th>Decompressor Pin</th>
                <th>Compactor Pin</th>
                <th>Chains</th>
                <th>Chain Names</th>
            </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
    </table>
    """


def _connectivity_summary_table(graph: dict) -> str:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    system_nodes = [n for n in nodes if n.get("type") != "scan_cell"]
    system_edges = [
        e for e in edges
        if ":cell:" not in str(e.get("source", ""))
        and ":cell:" not in str(e.get("target", ""))
    ]

    node_rows = "".join(
        f"<tr><td class='mono'>{_esc(n.get('id'))}</td>"
        f"<td>{_esc(n.get('type'))}</td>"
        f"<td>{_esc(n.get('label'))}</td></tr>"
        for n in system_nodes
    )
    edge_rows = "".join(
        f"<tr><td class='mono'>{_esc(e.get('source'))}</td>"
        f"<td class='mono'>{_esc(e.get('target'))}</td>"
        f"<td>{_esc(e.get('edge_type'))}</td></tr>"
        for e in system_edges
    )
    return f"""
    <p class="section-desc">
        System-level DFT connectivity (JTAG → TAP → EDT → chains). Full cell-level graph
        is omitted here ({graph.get('node_count', 0):,} nodes, {graph.get('edge_count', 0):,} edges).
    </p>
    <h4>System Nodes ({len(system_nodes)})</h4>
    <table>
        <thead><tr><th>Node ID</th><th>Type</th><th>Label</th></tr></thead>
        <tbody>{node_rows}</tbody>
    </table>
    <h4>System Edges ({len(system_edges)})</h4>
    <table>
        <thead><tr><th>Source</th><th>Target</th><th>Edge Type</th></tr></thead>
        <tbody>{edge_rows}</tbody>
    </table>
    """


def render_topology_section_html(
    topology: dict,
    failing_chains: set[str] | None = None,
    failing_chain_ids: set[str] | None = None,
) -> str:
    """Render FR-003 topology section HTML from build_topology_analysis output."""
    failing_chains = failing_chains or set()
    failing_chain_ids = failing_chain_ids or set()

    if topology.get("status") == "no_topology_loaded":
        return "<p>No scan topology loaded. Load STIL or hardware topology markdown first.</p>"

    summary = topology.get("summary") or {}
    balance = topology.get("chain_balance") or {}
    shared = topology.get("shared_resources") or {}
    compression = topology.get("compression_association") or {}
    graph = topology.get("connectivity_graph") or {}
    chains = topology.get("chains") or []
    die_ctx = summary.get("die_context_from_logs") or {}

    comp = compression.get("compression_ratio")
    balance_status = "Balanced" if balance.get("is_balanced") else "Imbalanced"

    summary_cards = f"""
    <div class="charts-row" style="margin-bottom: 20px;">
        <div class="chart-box" style="align-items: flex-start;">
            <div class="chart-title">Topology Coverage</div>
            <p><strong>{topology.get('number_of_scan_chains', 0)}</strong> scan chains</p>
            <p><strong>{summary.get('total_flip_flops', 0):,}</strong> total flip-flops</p>
            <p><strong>{summary.get('logs_analyzed', 0)}</strong> ATE logs analyzed</p>
            <p><strong>{summary.get('failure_records_analyzed', 0):,}</strong> failure records</p>
        </div>
        <div class="chart-box" style="align-items: flex-start;">
            <div class="chart-title">EDT Compression</div>
            <p>Logic: <span class="mono">{_esc(compression.get('compression_logic'))}</span></p>
            <p>Ratio: <strong>{comp}x</strong> ({compression.get('decompressor_channels', 0)} decomp /
               {compression.get('compactor_channels', 0)} compact channels)</p>
            <p>Chain balance: <strong>{balance_status}</strong>
               (imbalance {balance.get('imbalance_pct', 0)}%)</p>
        </div>
    </div>
    """

    balance_table = f"""
    <table>
        <thead>
            <tr>
                <th>Min Length</th><th>Max Length</th><th>Mean</th>
                <th>Std Dev</th><th>Variance</th><th>Imbalance %</th><th>Balanced</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td class="mono">{balance.get('min_length', 0)}</td>
                <td class="mono">{balance.get('max_length', 0)}</td>
                <td class="mono">{balance.get('mean_length', 0)}</td>
                <td class="mono">{balance.get('std_length', 0)}</td>
                <td class="mono">{balance.get('length_variance', 0)}</td>
                <td class="mono">{balance.get('imbalance_pct', 0)}%</td>
                <td>{'Yes' if balance.get('is_balanced') else 'No'}</td>
            </tr>
        </tbody>
    </table>
    """

    registry_rows = []
    cell_summary_rows = []
    for ch in chains:
        short = ch.get("chain_short_name") or ch.get("chain_name") or ""
        cid = ch.get("scan_chain_id") or ""
        has_fail = short in failing_chains or cid in failing_chain_ids
        fail_badge = (
            '<span class="badge badge-shift">FAILING</span>' if has_fail
            else '<span class="badge badge-low">CLEAN</span>'
        )
        comp_assoc = ch.get("compression_association") or {}
        cell_order = ch.get("scan_cell_order") or []
        first_cells = ", ".join(_esc(c) for c in cell_order[:3])
        last_cells = ", ".join(_esc(c) for c in cell_order[-3:]) if len(cell_order) > 3 else first_cells
        conn = ch.get("scan_cell_connectivity") or []
        conn_count = len(conn)

        registry_rows.append(f"""
        <tr>
            <td class="mono" style="font-weight: bold;">{_esc(short)}</td>
            <td class="mono" style="font-size: 11px;">{_esc(cid)}</td>
            <td class="mono">{_esc(ch.get('instance_type'))}</td>
            <td class="mono">{ch.get('chain_length', 0)}</td>
            <td class="mono">{_esc(ch.get('scan_input_si'))}</td>
            <td class="mono">{_esc(ch.get('scan_output_so'))}</td>
            <td class="mono">{_esc(ch.get('clock_domain'))}</td>
            <td class="mono">{_esc(ch.get('scan_enable_se'))}</td>
            <td class="mono">{_esc(comp_assoc.get('decompressor_pin'))}</td>
            <td class="mono">{_esc(comp_assoc.get('compactor_pin'))}</td>
            <td class="mono" style="color: #4f46e5;">{_esc(comp_assoc.get('hierarchical_path'))}</td>
            <td>{fail_badge}</td>
        </tr>
        """)

        cell_summary_rows.append(f"""
        <tr>
            <td class="mono" style="font-weight: bold;">{_esc(short)}</td>
            <td class="mono">{len(cell_order)}</td>
            <td class="mono" style="font-size: 11px;">{first_cells}</td>
            <td class="mono" style="font-size: 11px;">{last_cells}</td>
            <td class="mono">{conn_count}</td>
            <td class="mono">{_esc(ch.get('scan_input_si'))} → … → {_esc(ch.get('scan_output_so'))}</td>
        </tr>
        """)

    die_section = ""
    if die_ctx:
        bbox = die_ctx.get("die_bbox_mm") or {}
        die_section = f"""
        <h3>3.8 Die Context from Logs</h3>
        <table>
            <thead>
                <tr>
                    <th>Logs</th><th>Die Row Range</th><th>Die Col Range</th>
                    <th>Wafer X Mean (mm)</th><th>Wafer Y Mean (mm)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td class="mono">{die_ctx.get('logs_analyzed', 0)}</td>
                    <td class="mono">{die_ctx.get('die_row_range', [])}</td>
                    <td class="mono">{die_ctx.get('die_col_range', [])}</td>
                    <td class="mono">{die_ctx.get('wafer_x_mean', 'N/A')}</td>
                    <td class="mono">{die_ctx.get('wafer_y_mean', 'N/A')}</td>
                </tr>
            </tbody>
        </table>
        <p class="section-desc">Die bounding box (mm): x1={bbox.get('x1_mean', 'N/A')},
           y1={bbox.get('y1_mean', 'N/A')}, x2={bbox.get('x2_mean', 'N/A')},
           y2={bbox.get('y2_mean', 'N/A')}</p>
        """

    failing_count = sum(
        1 for ch in chains
        if (ch.get("chain_short_name") in failing_chains
            or ch.get("scan_chain_id") in failing_chain_ids)
    )

    return f"""
    <p class="section-desc">
        Complete FR-003 topology analysis from STIL design definitions and all ATE log metadata.
        Includes chain identity, cell order, connectivity, clock domains, scan-enable, EDT compression,
        physical placement, chain balance, and shared resources.
    </p>
    <h3>3.1 Topology Summary</h3>
    {summary_cards}

    <h3>3.2 Chain Balance Analysis</h3>
    {balance_table}

    <h3>3.3 Shared Resources</h3>
    <h4>Shared Clock Domains</h4>
    {_shared_resource_table(shared.get("shared_clocks", []), "resource")}
    <h4>Shared Scan Enable Signals</h4>
    {_shared_resource_table(shared.get("shared_scan_enable", []), "resource")}
    <h4>Shared Decompressor Channels</h4>
    {_shared_resource_table(shared.get("shared_decompressor_channels", []), "resource")}
    <h4>Shared Scan Inputs</h4>
    {_shared_resource_table(shared.get("shared_scan_inputs", []), "resource")}

    <h3>3.4 EDT Compression Association</h3>
    {_compression_channel_table(compression.get("channel_mapping", []))}

    <h3>3.5 Connectivity Graph Summary</h3>
    {_connectivity_summary_table(graph)}

    <h3>3.6 Complete Scan Chain Registry</h3>
    <p class="section-desc">
        All {len(chains)} design chains. {failing_count} chain(s) have failure records in the active dataset.
    </p>
    <table>
        <thead>
            <tr>
                <th>Chain</th><th>Chain ID</th><th>Instance</th><th>Length</th>
                <th>Scan In</th><th>Scan Out</th><th>Clock</th><th>Scan Enable</th>
                <th>Decompressor</th><th>Compactor</th><th>Hierarchical Path</th><th>Status</th>
            </tr>
        </thead>
        <tbody>{"".join(registry_rows)}</tbody>
    </table>

    <h3>3.7 Cell Order &amp; Connectivity Summary</h3>
    <table>
        <thead>
            <tr>
                <th>Chain</th><th>Cells</th><th>First Cells (SI side)</th>
                <th>Last Cells (SO side)</th><th>Connectivity Links</th><th>Scan Path</th>
            </tr>
        </thead>
        <tbody>{"".join(cell_summary_rows)}</tbody>
    </table>

    {die_section}

    <h3>3.9 Active Clocks &amp; Scan Enable</h3>
    <p><strong>Active clocks:</strong> <span class="mono">{_esc(", ".join(summary.get("active_clocks", [])))}</span></p>
    <p><strong>Scan enable signals:</strong> <span class="mono">{_esc(", ".join(summary.get("scan_enable_signals", [])))}</span></p>
    """
