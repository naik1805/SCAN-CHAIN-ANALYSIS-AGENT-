"""
Scan Diagnosis Report Generator (SCD-FR-008).

Generates a self-contained, interactive, and print-friendly HTML report
summarizing all diagnostic findings (FR-001 to FR-007).
Includes inline SVG charts for worst chains and classifications.
"""

from __future__ import annotations

import math
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from diagnosis_context import build_diagnosis_bundle, render_topology_section_html
from locate_cells import locate_failing_cells, enrich_with_positions
from stil_parser import resolve_chain, find_topology_md_file, parse_hardware_topology_md, parse_stil_scan_structures

# Color definitions matching dashboard style
COLORS = {
    "SHIFT_ISSUE": "#ef4444",
    "CAPTURE_TIMING_SETUP": "#3b82f6",
    "CAPTURE_TIMING_SETUP_ANOMALY": "#1d4ed8",
    "CAPTURE_TIMING_HOLD": "#10b981",
    "CAPTURE_TIMING_HOLD_ANOMALY": "#047857",
    "CAPTURE_CELL_DEFECT": "#8b5cf6",
    "PRIMARY_BAR": "#2563eb",
}


def _polar_to_cartesian(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg - 90)
    return cx + r * math.cos(angle_rad), cy + r * math.sin(angle_rad)


def _get_donut_slice_path(cx: float, cy: float, r_in: float, r_out: float, start_angle: float, end_angle: float) -> str:
    if end_angle - start_angle >= 360:
        end_angle = start_angle + 359.99
    x_out_start, y_out_start = _polar_to_cartesian(cx, cy, r_out, start_angle)
    x_out_end, y_out_end = _polar_to_cartesian(cx, cy, r_out, end_angle)
    x_in_start, y_in_start = _polar_to_cartesian(cx, cy, r_in, start_angle)
    x_in_end, y_in_end = _polar_to_cartesian(cx, cy, r_in, end_angle)
    
    large_arc = "1" if (end_angle - start_angle) > 180 else "0"
    
    path = f"M {x_out_start} {y_out_start} "
    path += f"A {r_out} {r_out} 0 {large_arc} 1 {x_out_end} {y_out_end} "
    path += f"L {x_in_end} {y_in_end} "
    path += f"A {r_in} {r_in} 0 {large_arc} 0 {x_in_start} {y_in_start} "
    path += "Z"
    return path


def generate_svg_donut(class_counts: dict[str, int]) -> str:
    """Generate inline SVG Donut chart with legend on the right."""
    total = sum(class_counts.values())
    if total == 0:
        return "<svg width='100%' height='200'><text x='50%' y='50%' text-anchor='middle' fill='#94a3b8'>No Data</text></svg>"
        
    cx, cy = 130, 130
    r_out, r_in = 100, 65
    
    slices = []
    current_angle = 0.0
    for cls, val in class_counts.items():
        if val == 0:
            continue
        percentage = (val / total) * 100
        angle = (val / total) * 360.0
        end_angle = current_angle + angle
        
        color = COLORS.get(cls, "#94a3b8")
        path = _get_donut_slice_path(cx, cy, r_in, r_out, current_angle, end_angle)
        
        slices.append(
            f'<path d="{path}" fill="{color}" stroke="#ffffff" stroke-width="1.5">'
            f'<title>{cls}: {val:,} ({percentage:.1f}%)</title>'
            f'</path>'
        )
        current_angle = end_angle

    # Build Legend
    legend = []
    y_pos = 35
    for cls, val in class_counts.items():
        if val == 0:
            continue
        percentage = (val / total) * 100
        color = COLORS.get(cls, "#94a3b8")
        label = cls.replace("CAPTURE_TIMING_", "").replace("CAPTURE_", "")
        legend.append(
            f'<g transform="translate(280, {y_pos})">'
            f'  <circle cx="0" cy="0" r="6" fill="{color}" />'
            f'  <text x="15" y="4" font-family="sans-serif" font-size="12" fill="#334155" font-weight="600">{label}</text>'
            f'  <text x="15" y="18" font-family="monospace" font-size="11" fill="#64748b">{val:,} ({percentage:.1f}%)</text>'
            f'</g>'
        )
        y_pos += 35
        
    svg = f"""
    <svg width="550" height="260" viewBox="0 0 550 260">
        <g>{chr(10).join(slices)}</g>
        <g>
            <circle cx="{cx}" cy="{cy}" r="{r_in - 2}" fill="#ffffff" />
            <text x="{cx}" y="{cy - 5}" font-family="sans-serif" font-weight="bold" font-size="20" fill="#0f172a" text-anchor="middle">{total:,}</text>
            <text x="{cx}" y="{cy + 15}" font-family="sans-serif" font-size="11" fill="#64748b" text-anchor="middle">TOTAL FAILS</text>
        </g>
        <g>{chr(10).join(legend)}</g>
    </svg>
    """
    return svg


def generate_svg_bar(ranked_chains: pd.DataFrame) -> str:
    """Generate horizontal bar chart for all failing scan chains (no artificial cap)."""
    if ranked_chains.empty:
        return "<svg width='100%' height='200'><text x='50%' y='50%' text-anchor='middle' fill='#94a3b8'>No Data</text></svg>"

    # Show every ranked chain — height scales with count
    all_rows = ranked_chains.copy()
    max_fails = float(all_rows["failures"].max()) if len(all_rows) else 0.0

    pad_left = 140
    bar_height = 16
    spacing = 6
    chart_width = 380
    height = max(80, len(all_rows) * (bar_height + spacing) + 40)

    bars = []
    labels = []
    values = []

    for idx, (_, r) in enumerate(all_rows.iterrows()):
        y = idx * (bar_height + spacing) + 15
        chain = str(r["chain"])
        fails = int(r["failures"])
        pct = float(r["percentage"])
        w = (fails / max_fails) * chart_width if max_fails > 0 else 0
        w = max(w, 2.0)
        label = chain if len(chain) <= 18 else chain[:16] + "…"

        labels.append(
            f'<text x="{pad_left - 12}" y="{y + 12}" font-family="monospace" font-weight="bold" '
            f'font-size="11" fill="#334155" text-anchor="end">#{idx+1}: {label}</text>'
        )
        bars.append(
            f'<rect x="{pad_left}" y="{y}" width="{w}" height="{bar_height}" rx="3" fill="{COLORS["PRIMARY_BAR"]}">'
            f'<title>{chain}: {fails:,} fails ({pct:.1f}%)</title></rect>'
        )
        values.append(
            f'<text x="{pad_left + w + 8}" y="{y + 12}" font-family="monospace" font-size="10" '
            f'fill="#475569">{fails:,} ({pct:.1f}%)</text>'
        )

    svg_w = pad_left + chart_width + 120
    return f"""
    <svg width="100%" height="{height}" viewBox="0 0 {svg_w} {height}" preserveAspectRatio="xMinYMin meet"
         style="max-width:100%;height:auto;display:block;">
        <g>{chr(10).join(labels)}</g>
        <g>{chr(10).join(bars)}</g>
        <g>{chr(10).join(values)}</g>
    </svg>
    """


def generate_html_report(
    df: pd.DataFrame,
    chain_map: dict,
    output_path: Path,
    log_dir: str | Path | None = None,
    project_root: Path | None = None,
) -> None:
    """Generate and write the unified Scan Diagnosis Report to output_path."""
    if df.empty:
        raise ValueError("Cannot generate report from an empty failures DataFrame.")

    bundle = build_diagnosis_bundle(
        df, chain_map, log_dir=log_dir, project_root=project_root
    )
    topology = bundle["topology"]

    # -------------------------------------------------------------
    # 1. AGGREGATE STATS
    # -------------------------------------------------------------
    total_records = len(df)
    failing_chains_count = df["chain"].nunique()
    failing_flops_count = df["fail_flop_id"].nunique()
    lots_count = df["lot_id"].nunique()
    dice_count = len(df.groupby(["lot_id", "source_file"]))

    # Calculate cell coordinates for FR-009
    from debug_locations import calculate_cell_coordinates
    try:
        coords_df = calculate_cell_coordinates(df, chain_map)
        if not coords_df.empty:
            priority_map = {'High': 0, 'Medium': 1, 'Low': 2}
            coords_df['prio_val'] = coords_df['priority'].map(priority_map)
            coords_df = coords_df.sort_values(by=['prio_val', 'confidence'], ascending=[True, False]).drop(columns=['prio_val'])
    except Exception:
        coords_df = pd.DataFrame()

    # Resolve active STIL file
    from stil_parser import resolve_active_stil_file
    active_stil_path = resolve_active_stil_file(df)
    active_stil = active_stil_path.name if active_stil_path else "Unknown STIL"

    # -------------------------------------------------------------
    # 2. FR-001 / FR-004 PARETO WORST CHAINS (native Series.rank)
    # -------------------------------------------------------------
    from chain_ranking import rank_chains_by_frequency

    ranked_freq = rank_chains_by_frequency(df, method="dense")
    counts = ranked_freq.rename(columns={
        "fail_count": "failures",
        "fail_pct": "percentage",
        "cumulative_pct": "cum_percentage",
    }).copy() if not ranked_freq.empty else pd.DataFrame(
        columns=["chain", "failures", "percentage", "cum_percentage", "rank"]
    )

    topology_section_html = render_topology_section_html(
        topology,
        failing_chains=bundle["failing_chains"],
        failing_chain_ids=bundle["failing_chain_ids"],
    )

    # -------------------------------------------------------------
    # 4. FR-006 SCAN CHAIN BREAKS (exact localization)
    # -------------------------------------------------------------
    from chain_breaks import detect_chain_breaks

    breaks_df_full = detect_chain_breaks(df, chain_map)
    broken_chains = set()
    breaks_list = []
    if not breaks_df_full.empty:
        for _, br in breaks_df_full.iterrows():
            sf = br["source_file"]
            lot = br["lot_id"]
            ch = br["chain"]
            # Match FR-007 shift tagging: use source_file as stored on failures
            broken_chains.add((sf, lot, ch))
            # Also allow basename match used elsewhere
            broken_chains.add((Path(str(sf)).name, lot, ch))
            loc_status = str(br.get("location_status") or "UNCERTAIN")
            cand_bit = br.get("candidate_break_bit_position")
            if cand_bit is None or (isinstance(cand_bit, float) and pd.isna(cand_bit)):
                cand_bit = br.get("break_bit_position")
            exact_bit = br.get("exact_break_bit_position")
            if exact_bit is not None and isinstance(exact_bit, float) and pd.isna(exact_bit):
                exact_bit = None
            exact_cell = br.get("exact_break_cell")
            cand_cell = br.get("candidate_break_cell") or br.get("suspected_break_cell")
            breaks_list.append({
                "lot_id": lot,
                "source_file": Path(str(sf)).name,
                "chain": ch,
                "location_status": loc_status,
                "location_status_reason": br.get("location_status_reason"),
                "break_bit_position": int(cand_bit) if cand_bit is not None else None,
                "exact_break_bit_position": int(exact_bit) if exact_bit is not None else None,
                "exact_break_cell": exact_cell if loc_status == "CERTAIN" else "LOCATION_UNCERTAIN",
                "candidate_break_bit_position": int(cand_bit) if cand_bit is not None else None,
                "candidate_break_cell": cand_cell,
                "suspected_break_cell": cand_cell,
                "location_confidence": float(br.get("location_confidence", 0.0) or 0.0),
                "exact_agreement": float(br.get("exact_agreement", 0.0) or 0.0),
                "soft_agreement": float(br.get("soft_agreement", 0.0) or 0.0),
                "localization_method": br.get("localization_method"),
                "fail_count": int(br["fail_count"]),
                "unique_failing_positions": int(br["unique_failing_positions"]),
                "scan_in": br.get("scan_in"),
                "scan_out": br.get("scan_out"),
            })
    breaks_df = pd.DataFrame(breaks_list)

    enriched = enrich_with_positions(df, chain_map)
    # Rebuild broken_chains keys to match enriched source_file values
    if not enriched.empty and not breaks_df_full.empty:
        broken_chains = set()
        for _, br in breaks_df_full.iterrows():
            ch = br["chain"]
            lot = br["lot_id"]
            sf_name = Path(str(br["source_file"])).name
            for sf_val in enriched.loc[
                (enriched["lot_id"] == lot) & (enriched["chain"] == ch), "source_file"
            ].unique():
                if Path(str(sf_val)).name == sf_name or str(sf_val) == str(br["source_file"]):
                    broken_chains.add((sf_val, lot, ch))


    # -------------------------------------------------------------
    # 5. FR-007 SHIFT VS CAPTURE DIAGNOSTICS
    # -------------------------------------------------------------
    diagnoses = []
    class_counts = {
        "SHIFT_ISSUE": 0,
        "CAPTURE_TIMING_SETUP": 0,
        "CAPTURE_TIMING_SETUP_ANOMALY": 0,
        "CAPTURE_TIMING_HOLD": 0,
        "CAPTURE_TIMING_HOLD_ANOMALY": 0,
        "CAPTURE_CELL_DEFECT": 0
    }

    has_anomaly = "is_anomaly" in enriched.columns
    has_pred_rc = "predicted_root_cause" in enriched.columns

    for _, row in enriched.iterrows():
        sf = row.get("source_file")
        lot = row.get("lot_id")
        ch = row.get("chain")
        
        is_shift = (sf, lot, ch) in broken_chains
        
        setup_slack = row.get("setup_slack_ps")
        if pd.isna(setup_slack) or setup_slack is None:
            setup_slack = 0.0
        else:
            setup_slack = float(setup_slack)

        hold_slack = row.get("hold_slack_ps")
        if pd.isna(hold_slack) or hold_slack is None:
            hold_slack = 0.0
        else:
            hold_slack = float(hold_slack)

        is_anomaly = row.get("is_anomaly", 0) if has_anomaly else 0
        if pd.isna(is_anomaly) or is_anomaly is None:
            is_anomaly = 0
        else:
            is_anomaly = int(is_anomaly)

        if is_shift:
            cls = "SHIFT_ISSUE"
            details = f"Associated with scan chain break on chain {ch}."
        elif setup_slack < 0 and setup_slack <= hold_slack:
            if is_anomaly:
                cls = "CAPTURE_TIMING_SETUP_ANOMALY"
                details = f"Anomalous setup timing violation (slack: {setup_slack} ps)."
            else:
                cls = "CAPTURE_TIMING_SETUP"
                details = f"Setup timing violation (slack: {setup_slack} ps)."
        elif hold_slack < 0 and hold_slack < setup_slack:
            if is_anomaly:
                cls = "CAPTURE_TIMING_HOLD_ANOMALY"
                details = f"Anomalous hold timing violation (slack: {hold_slack} ps)."
            else:
                cls = "CAPTURE_TIMING_HOLD"
                details = f"Hold timing violation (slack: {hold_slack} ps)."
        else:
            cls = "CAPTURE_CELL_DEFECT"
            rc = row.get("predicted_root_cause", "UNKNOWN") if has_pred_rc else "UNKNOWN"
            details = f"Functional cell defect (RF predicted root cause: {rc})."

        class_counts[cls] += 1
        diagnoses.append({
            "lot_id": lot,
            "source_file": Path(sf).name if sf else "Unknown",
            "pattern_id": str(row.get("pattern_id")),
            "chain": ch,
            "flop_id": row.get("fail_flop_id"),
            "bit_position": int(row["bit_position"]) if pd.notna(row.get("bit_position")) else None,
            "classification": cls,
            "setup_slack_ps": int(setup_slack) if pd.notna(setup_slack) else None,
            "hold_slack_ps": int(hold_slack) if pd.notna(hold_slack) else None,
            "details": details
        })

    # -------------------------------------------------------------
    # 6. FR-002 SUSPECTED CELLS LOCALIZATION
    # -------------------------------------------------------------
    suspects = locate_failing_cells(df, chain_map, min_observations=1)
    if not suspects.empty:
        suspects = suspects.sort_values("confidence", ascending=False)

    # -------------------------------------------------------------
    # 7. FR-005 FAILURE CORRELATIONS
    # -------------------------------------------------------------
    numerical_cols = ["ir_drop_mv", "thermal_c", "setup_slack_ps", "hold_slack_ps", "ai_severity_score"]
    valid_num_cols = [col for col in numerical_cols if col in df.columns]
    unique_c = sorted(df["chain"].dropna().unique(), key=lambda c: int("".join(ch for ch in c if ch.isdigit()) or 0))
    
    corr_data = []
    for ch in unique_c:
        is_ch = (df["chain"] == ch).astype(int)
        row = {"chain": ch}
        for col in valid_num_cols:
            col_series = pd.to_numeric(df[col], errors="coerce")
            if col_series.nunique() > 1:
                r = is_ch.corr(col_series)
                row[col] = 0.0 if pd.isna(r) else round(r, 4)
            else:
                row[col] = 0.0
                
        # Primary Driver
        drivers = {col: row[col] for col in valid_num_cols}
        if drivers:
            prim_driver = max(drivers, key=lambda k: abs(drivers[k]))
            prim_val = drivers[prim_driver]
            row["primary_driver"] = prim_driver.replace("_", " ").upper()
            row["primary_val"] = prim_val
        else:
            row["primary_driver"] = "NONE"
            row["primary_val"] = 0.0

        # Categorical distributions for this chain
        chain_df = df[df["chain"] == ch]
        total_fails = len(chain_df)
        row["fail_count"] = total_fails
        
        # Fail Type
        ft_desc = []
        if total_fails > 0 and "fail_type" in chain_df.columns:
            counts_ft = chain_df["fail_type"].value_counts()
            for k, v in counts_ft.items():
                ft_desc.append(f"{k}: {round(float(v / total_fails * 100), 1)}%")
        row["fail_type_dist"] = ", ".join(ft_desc) if ft_desc else "N/A"
        
        # Failure Region
        reg_desc = []
        if total_fails > 0 and "failure_region" in chain_df.columns:
            counts_reg = chain_df["failure_region"].value_counts()
            for k, v in counts_reg.items():
                if pd.notna(k) and str(k).strip():
                    reg_desc.append(f"{k}: {round(float(v / total_fails * 100), 1)}%")
        row["region_dist"] = ", ".join(reg_desc) if reg_desc else "N/A"
        
        # Root Cause Hint / Predicted
        rc_desc = []
        if total_fails > 0:
            col_rc = "predicted_root_cause" if "predicted_root_cause" in chain_df.columns else "root_cause_hint"
            if col_rc in chain_df.columns:
                counts_rc = chain_df[col_rc].value_counts()
                for k, v in counts_rc.items():
                    if pd.notna(k) and str(k).strip():
                        rc_desc.append(f"{k}: {round(float(v / total_fails * 100), 1)}%")
        row["rc_dist"] = ", ".join(rc_desc) if rc_desc else "N/A"

        corr_data.append(row)
        
    corr_df = pd.DataFrame(corr_data)
    
    # Dump debug json for offline inspection
    import json
    debug_info = {
        "len_df": len(df),
        "columns": list(df.columns),
        "unique_chains_raw": [str(x) for x in df["chain"].dropna().unique()],
        "unique_c_sorted": [str(x) for x in unique_c],
        "valid_num_cols": [str(x) for x in valid_num_cols],
        "corr_df_empty": bool(corr_df.empty),
        "corr_df_len": len(corr_df),
        "corr_df_cols": [str(x) for x in corr_df.columns],
        "corr_data_len": len(corr_data)
    }
    try:
        Path("data/cache/debug_report_gen.json").write_text(json.dumps(debug_info, indent=2), encoding="utf-8")
    except Exception as e:
        import traceback
        try:
            Path("data/cache/debug_err.txt").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass

    capture_diagnoses = [d for d in diagnoses if d["classification"] != "SHIFT_ISSUE"]

    # FR-006 break table rows (CERTAIN vs UNCERTAIN — never claim exact for UNCERTAIN)
    if breaks_df.empty:
        breaks_section_html = "<p>No scan chain breaks detected in this dataset.</p>"
    else:
        break_rows_html = []
        for _, r in breaks_df.iterrows():
            loc = str(r.get("location_status") or "UNCERTAIN")
            certain = loc == "CERTAIN"
            exact_bit = r.get("exact_break_bit_position")
            if exact_bit is not None and isinstance(exact_bit, float) and pd.isna(exact_bit):
                exact_bit = None
            exact_bit_disp = exact_bit if certain and exact_bit is not None else "—"
            exact_cell_disp = r.get("exact_break_cell") if certain else "LOCATION_UNCERTAIN"
            cand_bit = r.get("candidate_break_bit_position")
            if cand_bit is None or (isinstance(cand_bit, float) and pd.isna(cand_bit)):
                cand_bit = r.get("break_bit_position")
            if cand_bit is None or (isinstance(cand_bit, float) and pd.isna(cand_bit)):
                cand_bit_disp = "—"
            else:
                cand_bit_disp = int(cand_bit)
            cand_cell = r.get("candidate_break_cell") or r.get("suspected_break_cell") or "—"
            status_color = "#059669" if certain else "#d97706"
            cell_style = "color: #dc2626; font-weight: bold;" if certain else "color: #64748b;"
            # Emphasize candidate bit for UNCERTAIN (exact bit stays —).
            cand_bit_style = (
                "font-weight: 700; color: #d97706;" if not certain else ""
            )
            break_rows_html.append(
                f"""
            <tr>
                <td class="mono">{r['lot_id']}</td>
                <td class="mono">{r['source_file']}</td>
                <td class="mono" style="font-weight: bold;">{r['chain']}</td>
                <td class="mono" style="font-weight: 700; color: {status_color};">{loc}</td>
                <td class="mono" style="{cand_bit_style}">{cand_bit_disp}</td>
                <td class="mono">{cand_cell}</td>
                <td class="mono">{exact_bit_disp}</td>
                <td class="mono" style="{cell_style}">{exact_cell_disp}</td>
                <td class="mono">{float(r.get('location_confidence', 0) or 0):.1%}</td>
                <td class="mono">{float(r.get('exact_agreement', 0) or 0):.1%}</td>
                <td class="mono">{r['fail_count']:,}</td>
                <td class="mono">{r['scan_in']} / {r['scan_out']}</td>
            </tr>
            """
            )
        breaks_section_html = f"""
    <span class="row-count">{len(breaks_df):,} break rows</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Lot ID</th>
                <th>Die File</th>
                <th>Chain</th>
                <th>Location Status</th>
                <th>Candidate Bit</th>
                <th>Candidate Cell</th>
                <th>Exact Break Bit</th>
                <th>Exact Break Cell</th>
                <th>Confidence (soft ±5)</th>
                <th>Exact Agree</th>
                <th>Fail Count</th>
                <th>Scan In/Out</th>
            </tr>
        </thead>
        <tbody>
            {"".join(break_rows_html)}
        </tbody>
    </table>
    </div>
    """

    # -------------------------------------------------------------
    # HTML SVG RENDERINGS
    # -------------------------------------------------------------
    donut_chart_svg = generate_svg_donut(class_counts)
    bar_chart_svg = generate_svg_bar(counts)

    # -------------------------------------------------------------
    # HTML TEMPLATE BUILD
    # -------------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DFT Scan Chain Diagnosis Report</title>
    <!-- report-layout-v2: uncapped tables, single-column charts, scroll wrappers -->
    <style>
        :root {{
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --slate-50: #f8fafc;
            --slate-100: #f1f5f9;
            --slate-200: #e2e8f0;
            --slate-700: #334155;
            --slate-800: #1e293b;
            --slate-900: #0f172a;
            --border: #e2e8f0;
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #f8fafc;
            color: var(--slate-800);
            line-height: 1.5;
            margin: 0;
            padding: 0;
        }}

        .wrapper {{
            max-width: 1000px;
            margin: 40px auto;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05);
            border: 1px solid var(--slate-200);
            padding: 40px;
        }}

        header {{
            border-bottom: 2px solid var(--slate-100);
            padding-bottom: 30px;
            margin-bottom: 35px;
        }}

        .logo-area {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            flex-wrap: wrap;
        }}

        h1 {{
            font-size: 26px;
            color: var(--slate-900);
            margin: 0;
            font-weight: 800;
            letter-spacing: -0.5px;
        }}

        .meta-tag {{
            font-family: monospace;
            background-color: var(--slate-100);
            color: var(--slate-700);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
        }}

        .grid-4 {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 16px;
            margin-top: 30px;
        }}

        .card {{
            background: var(--slate-50);
            border: 1px solid var(--slate-200);
            border-radius: 8px;
            padding: 16px 12px;
            text-align: center;
            min-width: 0;
        }}

        .card-num {{
            font-size: 22px;
            font-weight: 800;
            color: var(--primary);
            margin: 0;
            word-break: break-word;
        }}

        .card-lbl {{
            font-size: 11px;
            font-weight: 700;
            color: #64748b;
            margin: 6px 0 0 0;
            letter-spacing: 0.04em;
        }}

        h2 {{
            font-size: 20px;
            color: var(--slate-900);
            border-left: 4px solid var(--primary);
            padding-left: 12px;
            margin-top: 45px;
            margin-bottom: 12px;
            font-weight: 700;
            clear: both;
        }}

        .section-desc {{
            font-size: 14px;
            color: #64748b;
            margin-bottom: 16px;
        }}

        .row-count {{
            display: inline-block;
            margin: 0 0 10px 0;
            padding: 4px 10px;
            border-radius: 999px;
            background: var(--slate-100);
            color: var(--slate-700);
            font-size: 12px;
            font-weight: 600;
        }}

        .table-scroll {{
            width: 100%;
            max-width: 100%;
            overflow-x: auto;
            overflow-y: auto;
            max-height: 560px;
            border: 1px solid var(--border);
            border-radius: 8px;
            -webkit-overflow-scrolling: touch;
            contain: layout paint;
            isolation: isolate;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 0;
            font-size: 13px;
            table-layout: auto;
        }}

        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
            word-break: break-word;
            overflow-wrap: anywhere;
        }}

        .table-scroll th {{
            background-color: var(--slate-50);
            color: var(--slate-900);
            font-weight: 700;
            position: sticky;
            top: 0;
            z-index: 2;
            box-shadow: 0 1px 0 var(--border);
        }}

        th {{
            background-color: var(--slate-50);
            color: var(--slate-900);
            font-weight: 700;
        }}

        tr:hover td {{
            background-color: var(--slate-50);
        }}

        .mono {{
            font-family: 'JetBrains Mono', 'Courier New', monospace;
            font-size: 12px;
        }}

        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            white-space: nowrap;
        }}

        .badge-shift {{ background-color: #fee2e2; color: #dc2626; }}
        .badge-setup {{ background-color: #dbeafe; color: #2563eb; }}
        .badge-hold {{ background-color: #d1fae5; color: #059669; }}
        .badge-defect {{ background-color: #f3e8ff; color: #7c3aed; }}
        .badge-high {{ background-color: #fee2e2; color: #dc2626; }}
        .badge-med {{ background-color: #fef3c7; color: #d97706; }}
        .badge-low {{ background-color: #f1f5f9; color: #475569; }}

        .charts-row {{
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: 24px;
            margin-top: 28px;
            align-items: start;
        }}

        .chart-box {{
            background: #ffffff;
            border: 1px solid var(--slate-200);
            border-radius: 8px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            align-items: stretch;
            min-width: 0;
            overflow: visible;
        }}

        .chart-box svg {{
            max-width: 100%;
            height: auto;
            display: block;
        }}

        .chart-title {{
            font-size: 13px;
            font-weight: 700;
            color: var(--slate-900);
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        footer {{
            margin-top: 60px;
            padding-top: 20px;
            border-top: 1px solid var(--slate-200);
            text-align: center;
            font-size: 12px;
            color: #64748b;
            clear: both;
        }}

        @media (max-width: 900px) {{
            .wrapper {{ margin: 12px; padding: 20px; }}
            .grid-4 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}

        @media print {{
            body {{
                background-color: #ffffff;
            }}
            .wrapper {{
                box-shadow: none;
                border: none;
                margin: 0;
                padding: 0;
                max-width: none;
            }}
            .no-print {{
                display: none;
            }}
            .chart-box {{
                max-height: none;
                overflow: visible;
            }}
            h2 {{
                page-break-after: avoid;
            }}
            tr {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>

<div class="wrapper">
    <header>
        <div class="logo-area">
            <div>
                <h1>DFT SCAN DIAGNOSIS REPORT</h1>
                <p style="margin: 5px 0 0 0; color: #64748b; font-size: 14px;">Automated Diagnostic Summary & Yield Analysis</p>
            </div>
            <div>
                <span class="meta-tag">GEN_TIME: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</span>
            </div>
        </div>

        <div class="grid-4">
            <div class="card">
                <p class="card-num">{total_records:,}</p>
                <p class="card-lbl">FAIL RECORDS</p>
            </div>
            <div class="card">
                <p class="card-num">{failing_chains_count}</p>
                <p class="card-lbl">FAILING CHAINS</p>
            </div>
            <div class="card">
                <p class="card-num">{len(breaks_df)}</p>
                <p class="card-lbl">DETECTED BREAKS</p>
            </div>
            <div class="card">
                <p class="card-num">{dice_count}</p>
                <p class="card-lbl">AFFECTED DICE</p>
            </div>
        </div>

        <div style="margin-top: 20px; font-size: 13px; color: #475569;">
            <strong>Active STIL File:</strong> <span class="mono">{active_stil}</span> | 
            <strong>Total Lots Ingested:</strong> {lots_count}
        </div>
    </header>

    <h2>1. Executive Summary</h2>
    <p class="section-desc">Diagnostic overview of the scan test execution across lots.</p>
    <p>
        During test execution, a total of <strong>{total_records:,} failure records</strong> were collected and parsed across 
        <strong>{lots_count} lots</strong> (containing <strong>{dice_count} failing dice</strong>).
        Physical scan diagnostics identified <strong>{len(breaks_df)} scan chain breaks</strong> causing systematic shift-path failures.
        The remaining failure signatures were classified using timing slack parameters and anomalous behavior profiles, 
        separating capture timing violations (setup/hold) from functional cell defects.
    </p>

    <div class="charts-row">
        <div class="chart-box">
            <div class="chart-title">Failure Diagnostics Breakdown</div>
            {donut_chart_svg}
        </div>
        <div class="chart-box">
            <div class="chart-title">All Failing Scan Chains ({len(counts):,})</div>
            {bar_chart_svg}
        </div>
    </div>

    <h2>2. Failing Scan Chains (FR-001)</h2>
    <p class="section-desc">Identified failing scan chains with individual failure log counts.</p>
    <span class="row-count">{len(counts):,} chains</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th style="width: 10%;">Rank</th>
                <th style="width: 30%;">Scan Chain</th>
                <th style="width: 30%;">Fail Counts</th>
                <th style="width: 30%;">Percentage</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f"""
            <tr>
                <td>#{int(r['rank']) if 'rank' in r and pd.notna(r['rank']) else idx+1}</td>
                <td class="mono">{r['chain']}</td>
                <td class="mono">{r['failures']:,}</td>
                <td>{r['percentage']:.2f}%</td>
            </tr>
            """ for idx, r in counts.iterrows())}
        </tbody>
    </table>
    </div>

    <h2>3. Scan Chain Topology Map (FR-003)</h2>
    {topology_section_html}

    <h2>4. Identified Scan Chain Breaks (FR-006)</h2>
    <p class="section-desc">
        Break signatures are <strong>identified automatically</strong> by the diagnosis agent — no manual bit/cell selection is required.
        For each failing die and scan chain, the agent compares EXPECTED vs ACTUAL unload bitstreams per pattern,
        takes the first mismatch bit from ScanOut, forms a cross-pattern consensus, and maps the consensus bit index
        to the STIL <code>ScanCells</code> instance.
        <strong>Location status</strong> is gated for production honesty:
        <strong>CERTAIN</strong> only when soft agreement ≥ 70% (±5 bits) <em>and</em> ≥ 2 patterns agree;
        otherwise status is <strong>UNCERTAIN</strong> and Exact Break Cell is not claimed
        (<code>LOCATION_UNCERTAIN</code>) — <strong>Candidate Bit</strong> and Candidate Cell
        are still shown for review (Exact Break Bit stays <code>—</code>).
        Soft agreement itself has no artificial floor; low agreement stays low and keeps the row UNCERTAIN.
    </p>
    {breaks_section_html}

    <h2>5. Worst Scan Chains Pareto Ranking (FR-004)</h2>
    <p class="section-desc">Pareto ordering via native pandas Series.rank(method='dense', ascending=False) on failure counts.</p>
    <span class="row-count">{len(counts):,} ranked chains</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Rank</th>
                <th>Scan Chain</th>
                <th>Fails Count</th>
                <th>Individual Pct</th>
                <th>Cumulative Pct</th>
                <th>Status (Pareto 80% Rule)</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f"""
            <tr>
                <td>#{int(r['rank']) if 'rank' in r and pd.notna(r['rank']) else idx+1}</td>
                <td class="mono" style="font-weight: bold;">{r['chain']}</td>
                <td class="mono">{r['failures']:,}</td>
                <td>{r['percentage']:.2f}%</td>
                <td>{r['cum_percentage']:.2f}%</td>
                <td>
                    <span style="color: {'#e11d48; font-weight: 700;' if r['cum_percentage'] <= 80.0 or ( 'rank' in r and int(r['rank']) == 1) or idx == 0 else '#475569;'}">
                        { 'Vital Few (<= 80%)' if r['cum_percentage'] <= 80.0 or idx == 0 else 'Trivial Many (> 80%)' }
                    </span>
                </td>
            </tr>
            """ for idx, r in counts.iterrows())}
        </tbody>
    </table>
    </div>

    <h2>6. Suspected Failing Cells (FR-002)</h2>
    <p class="section-desc">
        <strong>Exact failing scan cell / flip-flop localization is performed automatically by this
        Scan Chain Diagnosis Agent (SCD-FR-002)</strong> — not by SmarTest.
        SmarTest / ATE logs provide failure signatures and chain/cycle correlation evidence;
        diagnosis tools are responsible for mapping those signatures to a specific scan cell.
        This agent does that by (1) extracting per-bit EXPECTED vs ACTUAL mismatches as
        <code>fail_flop_id</code> / bit position, (2) mapping the bit through STIL
        <code>ScanStructures</code> / <code>ScanCells</code> to a netlist cell name, and
        (3) scoring confidence from corroborating pattern observations on that chain.
        The table below lists the localized cell name, flip-flop ID, bit position, and confidence.
    </p>
    {f"<p>No suspected failing cell localizations found.</p>" if suspects.empty else f"""
    <span class="row-count">{len(suspects):,} suspected cells</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Scan Chain</th>
                <th>Instance</th>
                <th>Exact Cell Name</th>
                <th>Flip-Flop ID</th>
                <th>Bit Position</th>
                <th>Offset from Scan In</th>
                <th>Chain Length</th>
                <th>Observations</th>
                <th>Corroborating Patterns</th>
                <th>Chain Observations</th>
                <th>Confidence</th>
                <th>RF Predicted Root Cause</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f'''
            <tr>
                <td class="mono">{r['chain']}</td>
                <td class="mono">{r['instance'] if pd.notna(r['instance']) else 'other'}</td>
                <td class="mono" style="color: #059669; font-weight: bold;">{r['cell_name']}</td>
                <td class="mono">{r['fail_flop_id'] if pd.notna(r['fail_flop_id']) else 'N/A'}</td>
                <td class="mono">{int(r['bit_position']) if pd.notna(r['bit_position']) else 'N/A'}</td>
                <td class="mono">{int(r['offset_from_scan_in']) if pd.notna(r['offset_from_scan_in']) else 'N/A'}</td>
                <td class="mono">{int(r['chain_length']) if pd.notna(r['chain_length']) else 'N/A'}</td>
                <td class="mono">{int(r['observations'])}</td>
                <td class="mono">{int(r['corroborating_patterns']) if pd.notna(r['corroborating_patterns']) else int(r['observations'])}</td>
                <td class="mono">{int(r['chain_observations']) if pd.notna(r['chain_observations']) else 'N/A'}</td>
                <td class="mono" style="font-weight: bold;">{r['confidence']:.2%}</td>
                <td><span class="badge badge-defect">{r['dominant_root_cause'] or 'UNKNOWN'}</span></td>
            </tr>
            ''' for _, r in suspects.iterrows())}
        </tbody>
    </table>
    </div>
    """}


    <h2>7. Failure Correlation Analysis (FR-005)</h2>
    <p class="section-desc">Pearson correlation coefficient mapping of scan chains against physical and timing features.</p>
    <span class="row-count">{len(corr_df):,} chains × {len(valid_num_cols)} metrics</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Scan Chain</th>
                {"".join(f"<th>{col.replace('_', ' ').upper()}</th>" for col in valid_num_cols)}
            </tr>
        </thead>
        <tbody>
            {"".join(f"""
            <tr>
                <td class="mono" style="font-weight: bold;">{r['chain']}</td>
                {"".join(f'<td class="mono" style="color: {"#dc2626" if float(r[col]) > 0.4 else ("#2563eb" if float(r[col]) < -0.4 else "#334155")}; font-weight: {"bold" if abs(float(r[col])) > 0.4 else "normal"};">{r[col]}</td>' for col in valid_num_cols)}
            </tr>
            """ for _, r in corr_df.iterrows())}
        </tbody>
    </table>
    </div>

    <h3 style="margin-top: 25px;">7.2 Failure Signature & Physical Driver Details</h3>
    <p class="section-desc">Primary physical drivers and signature distributions for each failing scan chain.</p>
    <span class="row-count">{len(corr_df):,} chain signatures</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Scan Chain</th>
                <th>Fail Count</th>
                <th>Primary Physical Driver</th>
                <th>Fail Type Breakdown</th>
                <th>Root Cause Breakdown</th>
                <th>Spatial Region Breakdown</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f"""
            <tr>
                <td class="mono" style="font-weight: bold;">{r['chain']}</td>
                <td>{r['fail_count']}</td>
                <td class="mono" style="font-weight: bold; color: {"#dc2626" if abs(r['primary_val']) > 0.05 else "#334155"}">{r['primary_driver']} (r={r['primary_val']:.3f})</td>
                <td style="font-size: 11px;">{r['fail_type_dist']}</td>
                <td style="font-size: 11px;">{r['rc_dist']}</td>
                <td style="font-size: 11px;">{r['region_dist']}</td>
            </tr>
            """ for _, r in corr_df.iterrows())}
        </tbody>
    </table>
    </div>

    <h2>8. Shift vs. Capture Timing Analysis (FR-007)</h2>
    <p class="section-desc">Physical breakdown classifying failures by shift-path integrity failures vs capture timing errors.</p>
    <span class="row-count">{sum(1 for v in class_counts.values() if v > 0)} classifications · {total_records:,} fails</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Classification</th>
                <th>Fails Count</th>
                <th>Percentage</th>
                <th>Description</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f"""
            <tr>
                <td class="mono" style="font-weight: bold;">
                    <span class="badge badge-{'shift' if k == 'SHIFT_ISSUE' else ('setup' if 'SETUP' in k else ('hold' if 'HOLD' in k else 'defect'))}">{k}</span>
                </td>
                <td class="mono">{v:,}</td>
                <td>{(v/total_records)*100:.2f}%</td>
                <td>
                    { 'Fails on a scan chain with a shift-path break.' if k == 'SHIFT_ISSUE' else
                     ('Setup timing violation (setup_slack < 0)' if k == 'CAPTURE_TIMING_SETUP' else
                     ('Anomalous setup timing violation (outlier flagged by IsolationForest)' if k == 'CAPTURE_TIMING_SETUP_ANOMALY' else
                     ('Hold timing violation (hold_slack < 0)' if k == 'CAPTURE_TIMING_HOLD' else
                     ('Anomalous hold timing violation (outlier flagged by IsolationForest)' if k == 'CAPTURE_TIMING_HOLD_ANOMALY' else
                     'Fails under correct timing constraints, indicating logical cell defect.')))) }
                </td>
            </tr>
            """ for k, v in class_counts.items() if v > 0)}
        </tbody>
    </table>
    </div>

    <h3 style="margin-top: 25px;">8.2 Detailed Capture Violations Registry</h3>
    <p class="section-desc">Failing patterns classified as capture timing errors or cell defects (excluding systematic shift breaks).</p>
    {f"<p>No capture violations detected.</p>" if not capture_diagnoses else f"""
    <span class="row-count">{len(capture_diagnoses):,} capture diagnoses</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Lot ID</th>
                <th>Die File</th>
                <th>Scan Chain</th>
                <th>Pattern ID</th>
                <th>Failing Cell/Flop</th>
                <th>Classification</th>
                <th>Setup / Hold Slack (ps)</th>
                <th>Diagnostic Details</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f'''
            <tr>
                <td class="mono">{d['lot_id']}</td>
                <td class="mono">{d['source_file']}</td>
                <td class="mono" style="font-weight: bold;">{d['chain']}</td>
                <td class="mono">{d['pattern_id']}</td>
                <td class="mono" style="color: #4f46e5; font-weight: bold;">{d['flop_id']}</td>
                <td class="mono">
                    <span class="badge badge-{'setup' if 'SETUP' in d['classification'] else ('hold' if 'HOLD' in d['classification'] else 'defect')}">{d['classification']}</span>
                </td>
                <td class="mono">{d['setup_slack_ps'] if d['setup_slack_ps'] is not None else 'N/A'} / {d['hold_slack_ps'] if d['hold_slack_ps'] is not None else 'N/A'}</td>
                <td style="font-size: 11px;">{d['details']}</td>
            </tr>
            ''' for d in capture_diagnoses)}
        </tbody>
    </table>
    </div>
    """}

    <h2>9. Debug Location Recommendations (FR-009)</h2>
    <p class="section-desc">Physical (X, Y) coordinates recommended for physical debug inspection, derived via serpentine scan-chain routing geometry.</p>
    {f"<p>No debug location recommendations available.</p>" if coords_df.empty else f"""
    <span class="row-count">{len(coords_df):,} recommendations</span>
    <div class="table-scroll">
    <table>
        <thead>
            <tr>
                <th>Scan Cell</th>
                <th>Scan Chain</th>
                <th>Fail Flop ID</th>
                <th>Logical Offset</th>
                <th>Die Local X (µm)</th>
                <th>Die Local Y (µm)</th>
                <th>Wafer Occurrences (Lot / Die: X, Y mm)</th>
                <th>Debug Priority</th>
            </tr>
        </thead>
        <tbody>
            {"".join(f'''
            <tr>
                <td class="mono" style="font-weight: bold; color: #0f172a;">{r['cell_name']}</td>
                <td class="mono">{r['chain']}</td>
                <td class="mono">{r['fail_flop_id']}</td>
                <td class="mono">{r['offset_from_scan_in']}</td>
                <td class="mono">{r['x_local_um']:.2f}</td>
                <td class="mono">{r['y_local_um']:.2f}</td>
                <td style="font-size: 11px; line-height: 1.45;">
                    <span class="row-count" style="margin-bottom:6px;">{len(r['occurrences']):,} occurrence(s)</span><br/>
                    {"".join(f"&bull; {occ['lot_id']} / {occ['die_label']}: ({occ['wafer_x_mm']:.4f}, {occ['wafer_y_mm']:.4f})<br/>" for occ in r['occurrences'])}
                </td>
                <td>
                    <span class="badge badge-{"high" if str(r.get("priority","")).lower()=="high" else ("med" if str(r.get("priority","")).lower().startswith("med") else "low")}">{r['priority']}</span>
                </td>
            </tr>
            ''' for _, r in coords_df.iterrows())}
        </tbody>
    </table>
    </div>
    """}

    <footer style="margin-top: 50px; border-top: 1px solid #e2e8f0; padding-top: 15px; text-align: center; color: #64748b; font-size: 12px;">
        <p>Report Generated Automatically by Scan Diagnosis Agent</p>
    </footer>
</div>

</body>
</html>
"""

    output_path.write_text(html, encoding="utf-8")
