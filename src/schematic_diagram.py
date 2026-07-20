"""
Interactive scan-chain schematic HTML builder.

Renders a system-level topology diagram with clickable chain rows and an
integrated zoomed schematic that updates client-side (no Streamlit rerun).
"""

from __future__ import annotations

import re

import plotly.graph_objects as go


def _chain_sort_key(chain: str) -> int:
    digits = "".join(c for c in (chain or "") if c.isdigit())
    return int(digits) if digits else 0


def build_connectivity_plotly_figure(
    chains_detail: list[dict],
    compression: dict,
) -> go.Figure:
    """System-level DFT connectivity graph — chains only, no per-cell nodes."""
    if not chains_detail:
        fig = go.Figure()
        fig.update_layout(title="No connectivity data", height=300)
        return fig

    sorted_chains = sorted(chains_detail, key=lambda c: _chain_sort_key(c.get("chain_name", "")))
    n = len(sorted_chains)
    height = max(480, n * 26 + 120)

    col_x = {"jtag": 0, "tap": 1, "edt": 2, "decomp": 3.2, "chain": 4.8, "comp": 6.2}
    y_edt = 0.5

    chain_positions: dict[str, tuple[float, float]] = {}
    for i, ch in enumerate(sorted_chains):
        y = (i + 0.5) / n
        chain_positions[ch["scan_chain_id"]] = (col_x["chain"], y)

    decomp_chains: dict[str, list[float]] = {}
    comp_chains: dict[str, list[float]] = {}
    for ch in sorted_chains:
        dp = ch["compression_association"]["decompressor_pin"]
        cp = ch["compression_association"]["compactor_pin"]
        _, y = chain_positions[ch["scan_chain_id"]]
        decomp_chains.setdefault(dp, []).append(y)
        comp_chains.setdefault(cp, []).append(y)

    decomp_pos = {pin: (col_x["decomp"], sum(ys) / len(ys)) for pin, ys in decomp_chains.items()}
    comp_pos = {pin: (col_x["comp"], sum(ys) / len(ys)) for pin, ys in comp_chains.items()}

    fig = go.Figure()

    def _add_nodes(trace_name, xs, ys, texts, hovers, color, size, showlegend=True):
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers",
            name=trace_name,
            marker=dict(size=size, color=color, line=dict(width=1, color="#1f2937")),
            text=texts, hovertext=hovers, hoverinfo="text",
            showlegend=showlegend,
        ))

    _add_nodes(
        "Controller",
        [col_x["jtag"], col_x["tap"], col_x["edt"]],
        [y_edt, y_edt, y_edt],
        ["JTAG", "TAP", "EDT Engine"],
        ["JTAG Controller", "TAP Controller", "EDT Compression Engine"],
        "#06b6d4", 18,
    )

    _add_nodes(
        "Decompressor",
        [p[0] for p in decomp_pos.values()],
        [p[1] for p in decomp_pos.values()],
        [pin.replace("edt_channels_in", "Decomp") for pin in decomp_pos],
        [f"Decompressor: {pin}<br>Chains: {len(decomp_chains[pin])}" for pin in decomp_pos],
        "#3b82f6", 14,
    )

    chain_xs, chain_ys, chain_labels, chain_hovers = [], [], [], []
    for ch in sorted_chains:
        x, y = chain_positions[ch["scan_chain_id"]]
        inst = ch.get("instance_type", "")
        label = ch["chain_name"]
        chain_xs.append(x)
        chain_ys.append(y)
        chain_labels.append(label)
        chain_hovers.append(
            f"<b>{label}</b> [{inst}]<br>"
            f"Length: {ch['chain_length']} FFs<br>"
            f"SI: {ch['scan_input_si']}<br>"
            f"SO: {ch['scan_output_so']}<br>"
            f"Clock: {ch.get('clock_domain', 'N/A')}"
        )
    _add_nodes("Scan Chain", chain_xs, chain_ys, chain_labels, chain_hovers, "#10b981", 12)

    _add_nodes(
        "Compactor",
        [p[0] for p in comp_pos.values()],
        [p[1] for p in comp_pos.values()],
        [pin.replace("edt_channels_out", "Comp") for pin in comp_pos],
        [f"Compactor: {pin}<br>Chains: {len(comp_chains[pin])}" for pin in comp_pos],
        "#8b5cf6", 14,
    )

    edge_x, edge_y = [], []
    for x0, x1, y in [
        (col_x["jtag"], col_x["tap"], y_edt),
        (col_x["tap"], col_x["edt"], y_edt),
    ]:
        edge_x += [x0, x1, None]
        edge_y += [y, y, None]

    for pin, (dx, dy) in decomp_pos.items():
        edge_x += [col_x["edt"], dx, None]
        edge_y += [y_edt, dy, None]

    for ch in sorted_chains:
        cx, cy = chain_positions[ch["scan_chain_id"]]
        dp = ch["compression_association"]["decompressor_pin"]
        cp = ch["compression_association"]["compactor_pin"]
        dx, _ = decomp_pos[dp]
        kx, _ = comp_pos[cp]
        edge_x += [dx, cx, kx, None]
        edge_y += [cy, cy, cy, None]

    for pin, (kx, ky) in comp_pos.items():
        edge_x += [kx, col_x["edt"], None]
        edge_y += [ky, y_edt, None]

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1.2, color="rgba(148,163,184,0.45)"),
        hoverinfo="skip", showlegend=False,
    ))

    ratio = compression.get("compression_ratio", 0)
    fig.update_layout(
        title=dict(
            text=f"System-Level DFT Connectivity  ({n} chains · {ratio:.1f}x compression)",
            font=dict(size=14),
        ),
        height=height,
        margin=dict(l=40, r=40, t=50, b=30),
        plot_bgcolor="rgba(6,8,20,0.95)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False, zeroline=False, showticklabels=False,
            range=[-0.4, 6.8],
        ),
        yaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.04)",
            zeroline=False, showticklabels=False,
            range=[-0.02, 1.02],
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01,
            xanchor="right", x=1, font=dict(size=11),
        ),
        hovermode="closest",
    )

    for i, ch in enumerate(sorted_chains):
        _, y = chain_positions[ch["scan_chain_id"]]
        fig.add_annotation(
            x=col_x["chain"] + 0.22, y=y,
            text=ch["chain_name"],
            showarrow=False, xanchor="left",
            font=dict(size=9, color="#a7f3d0"),
        )

    return fig


def build_system_connectivity_data(
    chains_detail: list[dict],
    compression: dict,
    full_graph: dict | None = None,
) -> dict:
    """JSON-serializable system-level DFT graph for React (mirrors Plotly layout)."""
    if not chains_detail:
        return {
            "nodes": [],
            "edges": [],
            "stats": {
                "graph_nodes": 0,
                "graph_edges": 0,
                "chain_nodes": 0,
                "compression_ratio": 0,
            },
        }

    sorted_chains = sorted(chains_detail, key=lambda c: _chain_sort_key(c.get("chain_name", "")))
    n = len(sorted_chains)
    col_x = {"jtag": 0, "tap": 1, "edt": 2, "decomp": 3.2, "chain": 4.8, "comp": 6.2}
    y_edt = 0.5

    chain_positions: dict[str, tuple[float, float]] = {}
    for i, ch in enumerate(sorted_chains):
        y = (i + 0.5) / n
        chain_positions[ch["scan_chain_id"]] = (col_x["chain"], y)

    decomp_chains: dict[str, list[float]] = {}
    comp_chains: dict[str, list[float]] = {}
    for ch in sorted_chains:
        ca = ch.get("compression_association") or {}
        dp = ca.get("decompressor_pin")
        cp = ca.get("compactor_pin")
        _, y = chain_positions[ch["scan_chain_id"]]
        if dp:
            decomp_chains.setdefault(dp, []).append(y)
        if cp:
            comp_chains.setdefault(cp, []).append(y)

    decomp_pos = {pin: (col_x["decomp"], sum(ys) / len(ys)) for pin, ys in decomp_chains.items()}
    comp_pos = {pin: (col_x["comp"], sum(ys) / len(ys)) for pin, ys in comp_chains.items()}

    nodes: list[dict] = []
    edges: list[dict] = []

    def _node(nid: str, x: float, y: float, label: str, kind: str, hover: str = "") -> None:
        nodes.append({
            "id": nid,
            "x": x,
            "y": y,
            "label": label,
            "kind": kind,
            "hover": hover or label,
        })

    _node("jtag", col_x["jtag"], y_edt, "JTAG", "controller", "JTAG Controller")
    _node("tap", col_x["tap"], y_edt, "TAP", "controller", "TAP Controller")
    _node("edt", col_x["edt"], y_edt, "EDT Engine", "controller", "EDT Compression Engine")

    for pin, (dx, dy) in decomp_pos.items():
        short = pin.replace("edt_channels_in", "Decomp")
        _node(
            f"decomp:{pin}", dx, dy, short, "decompressor",
            f"Decompressor: {pin}<br>Chains: {len(decomp_chains[pin])}",
        )

    for ch in sorted_chains:
        cx, cy = chain_positions[ch["scan_chain_id"]]
        inst = ch.get("instance_type", "")
        label = ch.get("chain_name", "")
        hover = (
            f"{label} [{inst}] · {ch.get('chain_length')} FFs · "
            f"SI: {ch.get('scan_input_si')} · SO: {ch.get('scan_output_so')}"
        )
        nodes.append({
            "id": ch["scan_chain_id"],
            "x": cx,
            "y": cy,
            "label": label,
            "kind": "chain",
            "hover": hover,
            "details": {
                "chain_name": label,
                "instance_type": inst,
                "chain_length": ch.get("chain_length"),
                "scan_input_si": ch.get("scan_input_si"),
                "scan_output_so": ch.get("scan_output_so"),
                "clock_domain": ch.get("clock_domain"),
                "scan_enable_se": ch.get("scan_enable_se"),
            },
        })

    for pin, (kx, ky) in comp_pos.items():
        short = pin.replace("edt_channels_out", "Comp")
        _node(
            f"comp:{pin}", kx, ky, short, "compactor",
            f"Compactor: {pin}<br>Chains: {len(comp_chains[pin])}",
        )

    def _edge(a: str, b: str) -> None:
        edges.append({"from": a, "to": b})

    _edge("jtag", "tap")
    _edge("tap", "edt")
    for pin in decomp_pos:
        _edge("edt", f"decomp:{pin}")
    for ch in sorted_chains:
        ca = ch.get("compression_association") or {}
        dp = ca.get("decompressor_pin")
        cp = ca.get("compactor_pin")
        cid = ch["scan_chain_id"]
        if dp:
            _edge(f"decomp:{dp}", cid)
        if cp:
            _edge(cid, f"comp:{cp}")
    for pin in comp_pos:
        _edge(f"comp:{pin}", "edt")

    fg = full_graph or {}
    ratio = compression.get("compression_ratio", 0)
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "graph_nodes": fg.get("node_count", len(nodes)),
            "graph_edges": fg.get("edge_count", len(edges)),
            "chain_nodes": n,
            "compression_ratio": ratio,
        },
    }


def _decomp_channel(pin: str) -> str:
    if "[" in pin:
        return pin.split("[")[1][:-1]
    return pin


def _build_zoom_svg(
    chain: dict,
    suspect_positions: dict[int, dict],
    uid: str,
) -> tuple[str, int]:
    """Return zoomed chain SVG markup and its width."""
    scan_in = chain.get("scan_in") or "UNKNOWN"
    scan_out = chain.get("scan_out") or "UNKNOWN"
    decomp_pin = chain.get("decompressor_pin") or "UNKNOWN"
    comp_pin = chain.get("compactor_pin") or "UNKNOWN"
    length = chain.get("scan_length") or 234
    path_prefix = chain.get("hierarchical_path") or "U_core/unknown"

    cells_to_draw: list[tuple[int, str]] = []
    for i in range(min(3, length)):
        cells_to_draw.append((i, f"FF {i}"))
    if length > 6:
        cells_to_draw.append((-1, "..."))
    for i in range(max(length - 3, 3), length):
        cells_to_draw.append((i, f"FF {i}"))

    x_start = 220
    x_spacing = 75
    y_pos = 90
    cells_svg: list[str] = []

    for idx, (cell_pos, label) in enumerate(cells_to_draw):
        x = x_start + idx * x_spacing
        if cell_pos == -1:
            cells_svg.append(
                f'<text x="{x + 15}" y="{y_pos + 8}" fill="#9ca3af" '
                f'font-family="monospace" font-size="20" text-anchor="middle">...</text>'
            )
        else:
            is_suspect = cell_pos in suspect_positions
            if is_suspect:
                conf = suspect_positions[cell_pos]["confidence"]
                fill_color = "rgba(239, 68, 68, 0.15)"
                stroke_color = "#ef4444"
                glow = f'filter="url(#glow-red-{uid})"'
                text_color = "#fee2e2"
                tooltip = (
                    f"Position: {cell_pos}&#10;Path: {path_prefix}[{cell_pos}]"
                    f"&#10;Suspect! Confidence: {conf:.1%}"
                )
            else:
                fill_color = "rgba(16, 185, 129, 0.06)"
                stroke_color = "rgba(16, 185, 129, 0.4)"
                glow = f'filter="url(#glow-green-{uid})"'
                text_color = "#a7f3d0"
                tooltip = f"Position: {cell_pos}&#10;Path: {path_prefix}[{cell_pos}]"

            cells_svg.append(f"""
                <g {glow}>
                    <rect x="{x}" y="{y_pos - 20}" width="50" height="40" rx="6"
                          fill="{fill_color}" stroke="{stroke_color}" stroke-width="1.5" />
                    <text x="{x + 25}" y="{y_pos + 4}" fill="{text_color}"
                          font-family="sans-serif" font-size="10" font-weight="600"
                          text-anchor="middle">{label}</text>
                    <title>{tooltip}</title>
                </g>
            """)

            if idx < len(cells_to_draw) - 1:
                next_pos = cells_to_draw[idx + 1][0]
                if cell_pos != -1 and next_pos != -1:
                    cells_svg.append(
                        f'<path d="M {x + 50} {y_pos} L {x + x_spacing - 5} {y_pos}" '
                        f'stroke="#10b981" stroke-width="1.5" marker-end="url(#arrow-{uid})" />'
                    )
                elif cell_pos != -1 and next_pos == -1:
                    cells_svg.append(
                        f'<path d="M {x + 50} {y_pos} L {x + x_spacing - 5} {y_pos}" '
                        f'stroke="#10b981" stroke-width="1.5" stroke-dasharray="2 2" />'
                    )
                elif cell_pos == -1 and next_pos != -1:
                    cells_svg.append(
                        f'<path d="M {x + 35} {y_pos} L {x + x_spacing - 5} {y_pos}" '
                        f'stroke="#10b981" stroke-width="1.5" stroke-dasharray="2 2" '
                        f'marker-end="url(#arrow-{uid})" />'
                    )

    last_cell_x = x_start + (len(cells_to_draw) - 1) * x_spacing
    last_cell_end = last_cell_x + 50
    compactor_x = last_cell_end + 25
    scan_out_x = compactor_x + 85 + 25
    svg_width = scan_out_x + 85 + 15

    svg = f"""
    <svg width="100%" height="180" viewBox="0 0 {svg_width} 180" fill="none"
         xmlns="http://www.w3.org/2000/svg"
         style="background:rgba(17,24,39,0.45);border-radius:12px;
                border:1px solid rgba(255,255,255,0.05);padding:10px;">
        <defs>
            <marker id="arrow-{uid}" viewBox="0 0 10 10" refX="6" refY="5"
                    markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#10b981"/>
            </marker>
            <marker id="arrow-orange-{uid}" viewBox="0 0 10 10" refX="6" refY="5"
                    markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#f97316"/>
            </marker>
            <filter id="glow-red-{uid}" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="4" flood-color="#ef4444" flood-opacity="0.65"/>
            </filter>
            <filter id="glow-green-{uid}" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="#10b981" flood-opacity="0.25"/>
            </filter>
        </defs>
        <rect x="15" y="{y_pos - 35}" width="80" height="70" rx="6"
              fill="rgba(249,115,22,0.08)" stroke="rgba(249,115,22,0.25)" stroke-width="1.5"/>
        <text x="55" y="{y_pos - 15}" fill="#f97316" font-family="sans-serif"
              font-size="9" font-weight="700" text-anchor="middle">SCAN INPUT</text>
        <text x="55" y="{y_pos + 12}" fill="#ffedd5" font-family="monospace"
              font-size="10" text-anchor="middle">{scan_in}</text>
        <path d="M 95 {y_pos} L 115 {y_pos}" stroke="#f97316" stroke-width="1.5"
              marker-end="url(#arrow-orange-{uid})"/>
        <rect x="120" y="{y_pos - 35}" width="80" height="70" rx="6"
              fill="rgba(59,130,246,0.08)" stroke="rgba(59,130,246,0.25)" stroke-width="1.5"/>
        <text x="160" y="{y_pos - 15}" fill="#3b82f6" font-family="sans-serif"
              font-size="9" font-weight="700" text-anchor="middle">DECOMPRESSOR</text>
        <text x="160" y="{y_pos + 12}" fill="#dbeafe" font-family="monospace"
              font-size="9" text-anchor="middle">{_decomp_channel(decomp_pin)}</text>
        <path d="M 200 {y_pos} L 215 {y_pos}" stroke="#10b981" stroke-width="1.5"
              marker-end="url(#arrow-{uid})"/>
        {''.join(cells_svg)}
        <path d="M {last_cell_end} {y_pos} L {compactor_x - 5} {y_pos}" stroke="#10b981"
              stroke-width="1.5" marker-end="url(#arrow-{uid})"/>
        <rect x="{compactor_x}" y="{y_pos - 35}" width="85" height="70" rx="6"
              fill="rgba(59,130,246,0.08)" stroke="rgba(59,130,246,0.25)" stroke-width="1.5"/>
        <text x="{compactor_x + 42.5}" y="{y_pos - 15}" fill="#3b82f6" font-family="sans-serif"
              font-size="9" font-weight="700" text-anchor="middle">COMPACTOR</text>
        <text x="{compactor_x + 42.5}" y="{y_pos + 12}" fill="#dbeafe" font-family="monospace"
              font-size="9" text-anchor="middle">{_decomp_channel(comp_pin)}</text>
        <path d="M {compactor_x + 85} {y_pos} L {scan_out_x - 5} {y_pos}" stroke="#f97316"
              stroke-width="1.5" marker-end="url(#arrow-orange-{uid})"/>
        <rect x="{scan_out_x}" y="{y_pos - 35}" width="85" height="70" rx="6"
              fill="rgba(249,115,22,0.08)" stroke="rgba(249,115,22,0.25)" stroke-width="1.5"/>
        <text x="{scan_out_x + 42.5}" y="{y_pos - 15}" fill="#f97316" font-family="sans-serif"
              font-size="9" font-weight="700" text-anchor="middle">SCAN OUTPUT</text>
        <text x="{scan_out_x + 42.5}" y="{y_pos + 12}" fill="#ffedd5" font-family="monospace"
              font-size="10" text-anchor="middle">{scan_out}</text>
    </svg>
    """
    return svg, svg_width


def build_interactive_schematic_html(
    chain_entries: list[dict],
    default_uid: str = "c0",
) -> tuple[str, int]:
    """Build unified HTML with clickable system diagram + zoomed schematics.

    Each entry in *chain_entries* must include:
        uid, chain_name, instance_type, scan_length,
        scan_in, scan_out, decompressor_pin, compactor_pin,
        hierarchical_path, suspect_positions (optional dict)
    """
    if not chain_entries:
        return "<p>No chains available.</p>", 200

    num_chains = len(chain_entries)
    row_height = 24 if num_chains <= 24 else max(12, 550 // num_chains)
    svg_view_height = max(580, num_chains * row_height + 40)
    y_edt_center = svg_view_height // 2
    x_edt_out = 500
    x_label_start = 610

    curves_svg: list[str] = []
    rows_svg: list[str] = []
    zoom_panels: list[str] = []
    chain_meta_js: list[str] = []

    for i, entry in enumerate(chain_entries):
        uid = entry["uid"]
        ch_label = entry["chain_name"]
        inst = entry.get("instance_type", "")
        inst_short = "core" if inst == "core_inst" else ("phy" if inst == "phy_inst" else inst)
        display_label = f"{ch_label} ({inst_short})"
        ch_len = entry.get("scan_length", 234)
        is_default = uid == default_uid
        y_row = 15 + i * row_height

        curve_color = "#38bdf8" if is_default else "rgba(14, 165, 233, 0.2)"
        curve_width = "2.5" if is_default else "1"
        curve_opacity = "1.0" if is_default else "0.45"
        curves_svg.append(f"""
            <path id="curve-{uid}" class="chain-curve"
                  d="M {x_edt_out} {y_edt_center} C {x_edt_out + 45} {y_edt_center},
                     {x_label_start - 55} {y_row + 10}, {x_label_start - 10} {y_row + 10}"
                  stroke="{curve_color}" stroke-width="{curve_width}"
                  stroke-opacity="{curve_opacity}" fill="none"/>
        """)

        active_cls = " active" if is_default else ""
        rows_svg.append(f"""
            <g class="chain-row{active_cls}" id="row-{uid}"
               onclick="selectChain('{uid}')" style="cursor:pointer">
                <rect x="{x_label_start - 8}" y="{y_row - 4}" width="320" height="{row_height + 4}"
                      fill="transparent"/>
                <text x="{x_label_start}" y="{y_row + 14}"
                      class="ff-label" fill="{'#e0f2fe' if is_default else 'rgba(156,163,175,0.5)'}"
                      font-family="monospace" font-size="9">[{ch_len} FFs]</text>
                <text x="{x_label_start + 65}" y="{y_row + 14}"
                      class="ch-label" fill="{'#38bdf8' if is_default else '#f3f4f6'}"
                      font-family="sans-serif" font-size="10"
                      font-weight="{'bold' if is_default else 'normal'}">{display_label}</text>
                <rect x="{x_label_start + 115}" y="{y_row}" width="180" height="20" rx="4"
                      class="ch-block" fill="{'rgba(56,189,248,0.12)' if is_default else 'rgba(255,255,255,0.01)'}"
                      stroke="{'#38bdf8' if is_default else 'rgba(255,255,255,0.08)'}" stroke-width="1"/>
                <text x="{x_label_start + 205}" y="{y_row + 13}"
                      class="ch-block-text" fill="{'#38bdf8' if is_default else 'rgba(156,163,175,0.6)'}"
                      font-family="monospace" font-size="9" font-weight="600"
                      text-anchor="middle">[{ch_label.upper()}]</text>
            </g>
        """)

        zoom_svg, _ = _build_zoom_svg(entry, entry.get("suspect_positions", {}), uid)
        display = "block" if is_default else "none"
        zoom_panels.append(
            f'<div class="zoom-panel" id="zoom-{uid}" style="display:{display};">{zoom_svg}</div>'
        )

        scan_in = entry.get("scan_in", "")
        scan_out = entry.get("scan_out", "")
        decomp = entry.get("decompressor_pin", "")
        comp = entry.get("compactor_pin", "")
        chain_meta_js.append(
            f"'{uid}': {{label: '{display_label}', length: {ch_len}, "
            f"si: '{scan_in}', so: '{scan_out}', decomp: '{decomp}', comp: '{comp}'}}"
        )

    default_entry = next((e for e in chain_entries if e["uid"] == default_uid), chain_entries[0])
    default_label = default_entry["chain_name"]
    inst = default_entry.get("instance_type", "")
    inst_short = "core" if inst == "core_inst" else ("phy" if inst == "phy_inst" else inst)
    default_display = f"{default_label} ({inst_short})"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body {{ margin:0; padding:0; background:transparent; font-family:sans-serif; }}
  .chain-row:hover .ch-block {{ fill:rgba(56,189,248,0.18) !important; stroke:#38bdf8 !important; }}
  .chain-row:hover .ch-label {{ fill:#38bdf8 !important; }}
  .chain-row.active .ch-block {{ fill:rgba(56,189,248,0.22) !important; stroke:#38bdf8 !important; }}
  .chain-row.active .ch-label {{ fill:#38bdf8 !important; font-weight:bold; }}
  .info-bar {{
    margin:10px 0 6px; padding:10px 14px; background:rgba(17,24,39,0.6);
    border:1px solid rgba(255,255,255,0.08); border-radius:8px; color:#e5e7eb; font-size:13px;
  }}
  .info-bar strong {{ color:#38bdf8; }}
  .hint {{ color:#9ca3af; font-size:12px; margin-bottom:8px; }}
  svg {{ display:block; width:100%; }}
</style>
</head>
<body>
<p class="hint">Click any chain row in the system diagram to update the zoomed schematic below.</p>
<svg width="100%" height="{svg_view_height}" viewBox="0 0 940 {svg_view_height}" fill="none"
     xmlns="http://www.w3.org/2000/svg"
     style="background:#060814;border-radius:12px;border:1px solid rgba(255,255,255,0.03);padding:10px;">
  <defs>
    <marker id="arrow-red-sys" viewBox="0 0 10 10" refX="6" refY="5"
            markerWidth="5" markerHeight="5" orient="auto-start-reverse">
      <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#ef4444"/>
    </marker>
    <filter id="glow-cyan-sys" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#06b6d4" flood-opacity="0.8"/>
    </filter>
    <filter id="glow-purple-sys" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#a855f7" flood-opacity="0.8"/>
    </filter>
  </defs>
  {''.join(curves_svg)}
  {''.join(rows_svg)}
  <g filter="url(#glow-cyan-sys)">
    <rect x="40" y="{y_edt_center - 30}" width="110" height="60" rx="8"
          fill="rgba(6,182,212,0.04)" stroke="#0ea5e9" stroke-width="1.5"/>
    <text x="95" y="{y_edt_center + 5}" fill="#fff" font-size="13" font-weight="700"
          text-anchor="middle">JTAG</text>
  </g>
  <path d="M 150 {y_edt_center} L 185 {y_edt_center}" stroke="#ef4444" stroke-width="2.5"
        marker-end="url(#arrow-red-sys)"/>
  <g filter="url(#glow-cyan-sys)">
    <rect x="190" y="{y_edt_center - 30}" width="110" height="60" rx="8"
          fill="rgba(6,182,212,0.04)" stroke="#0ea5e9" stroke-width="1.5"/>
    <text x="245" y="{y_edt_center + 5}" fill="#fff" font-size="13" font-weight="700"
          text-anchor="middle">TAP</text>
  </g>
  <path d="M 300 {y_edt_center} L 335 {y_edt_center}" stroke="#ef4444" stroke-width="2.5"
        marker-end="url(#arrow-red-sys)"/>
  <g filter="url(#glow-purple-sys)">
    <rect x="340" y="{y_edt_center - 60}" width="160" height="120" rx="16"
          fill="rgba(168,85,247,0.04)" stroke="#a855f7" stroke-width="1.5"/>
    <text x="420" y="{y_edt_center - 5}" fill="#fff" font-size="14" font-weight="700"
          text-anchor="middle">EDT ENGINE</text>
    <text x="420" y="{y_edt_center + 15}" fill="#d946ef" font-size="8" font-weight="700"
          text-anchor="middle">COMPRESSION LOGIC</text>
  </g>
</svg>

<div class="info-bar" id="chain-info">
  <strong>{default_display}</strong> — {default_entry.get('scan_length', 234)} FFs ·
  SI: <code>{default_entry.get('scan_in', '')}</code> ·
  SO: <code>{default_entry.get('scan_out', '')}</code> ·
  Decompressor: <code>{default_entry.get('decompressor_pin', '')}</code> ·
  Compactor: <code>{default_entry.get('compactor_pin', '')}</code>
</div>

<h4 style="color:#e5e7eb;margin:12px 0 6px;font-size:14px;">Zoomed Scan Chain Schematic</h4>
{''.join(zoom_panels)}

<script>
const chainMeta = {{{', '.join(chain_meta_js)}}};

function selectChain(uid) {{
  document.querySelectorAll('.zoom-panel').forEach(el => el.style.display = 'none');
  const panel = document.getElementById('zoom-' + uid);
  if (panel) panel.style.display = 'block';

  document.querySelectorAll('.chain-row').forEach(el => el.classList.remove('active'));
  const row = document.getElementById('row-' + uid);
  if (row) row.classList.add('active');

  document.querySelectorAll('.chain-curve').forEach(el => {{
    el.setAttribute('stroke', 'rgba(14, 165, 233, 0.2)');
    el.setAttribute('stroke-width', '1');
    el.setAttribute('stroke-opacity', '0.45');
  }});
  const curve = document.getElementById('curve-' + uid);
  if (curve) {{
    curve.setAttribute('stroke', '#38bdf8');
    curve.setAttribute('stroke-width', '2.5');
    curve.setAttribute('stroke-opacity', '1.0');
  }}

  const m = chainMeta[uid];
  if (m) {{
    document.getElementById('chain-info').innerHTML =
      '<strong>' + m.label + '</strong> — ' + m.length + ' FFs · ' +
      'SI: <code>' + m.si + '</code> · SO: <code>' + m.so + '</code> · ' +
      'Decompressor: <code>' + m.decomp + '</code> · Compactor: <code>' + m.comp + '</code>';
  }}
}}
</script>
</body>
</html>"""
    total_height = svg_view_height + 280
    return html, total_height
