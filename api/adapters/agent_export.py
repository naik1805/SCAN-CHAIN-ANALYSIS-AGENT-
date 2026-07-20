"""
Persist agent diagnosis outputs as JSON artifacts under ``output/``.

Two layers:
  1. Per-requirement exports (SCD-FR-001 … FR-009) — audit trail per spec item.
  2. Dashboard snapshot (SCD-dashboard.json) — same shape React consumes (all KPIs + tables).
  3. Manifest (SCD-export_manifest.json) — maps each KPI card to its requirement artifact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.adapters.data_loader import load_failures, select_logs
from api.adapters.diagnosis_service import get_dashboard
from api.adapters.paths import OUTPUT_DIR, PROJECT_ROOT

# KPI id (React) → requirement artifact produced by src/export_outputs.py
KPI_ARTIFACT_MAP: list[dict[str, str]] = [
    {"kpi_id": "failing_chains", "section": "overview", "requirement_id": "SCD-FR-001", "artifact": "SCD-FR-001_failing_scan_chains.json"},
    {"kpi_id": "failing_cells", "section": "overview", "requirement_id": "SCD-FR-002", "artifact": "SCD-FR-002_suspected_failing_cells.json"},
    {"kpi_id": "chain_breaks", "section": "overview", "requirement_id": "SCD-FR-006", "artifact": "SCD-FR-006_scan_chain_breaks.json"},
    {"kpi_id": "shift_capture", "section": "overview", "requirement_id": "SCD-FR-007", "artifact": "SCD-FR-007_shift_capture_diagnosis.json"},
    {"kpi_id": "topology_chains", "section": "engineering", "requirement_id": "SCD-FR-003", "artifact": "SCD-FR-003_scan_topology.json"},
    {"kpi_id": "ranked_chains", "section": "engineering", "requirement_id": "SCD-FR-004", "artifact": "SCD-FR-004_chain_failure_ranking.json"},
    {"kpi_id": "failure_correlations", "section": "engineering", "requirement_id": "SCD-FR-005", "artifact": "SCD-FR-005_failure_correlation.json"},
    {"kpi_id": "top_failing_chain", "section": "engineering", "requirement_id": "SCD-FR-004", "artifact": "SCD-FR-004_chain_failure_ranking.json"},
    {"kpi_id": "diagnosis_reports", "section": "ai", "requirement_id": "SCD-FR-008", "artifact": "SCD-FR-008_scan_diagnosis_report.html"},
    {"kpi_id": "debug_locations", "section": "ai", "requirement_id": "SCD-FR-009", "artifact": "SCD-FR-009_debug_locations.json"},
    {"kpi_id": "avg_confidence", "section": "ai", "requirement_id": "SCD-FR-002", "artifact": "SCD-FR-002_suspected_failing_cells.json"},
    {"kpi_id": "pending_reviews", "section": "ai", "requirement_id": "SCD-FR-008", "artifact": "SCD-FR-008_scan_diagnosis_report.html"},
]

DASHBOARD_SNAPSHOT = "SCD-dashboard.json"
EXPORT_MANIFEST = "SCD-export_manifest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_requirement_exports(max_per_lot: int | None = None) -> dict[str, Any]:
    """Run ``src/export_outputs.py`` (full dataset when max_per_lot is None)."""
    script = PROJECT_ROOT / "src" / "export_outputs.py"
    cmd = [sys.executable, str(script)]
    if max_per_lot is not None and max_per_lot > 0:
        cmd.extend(["--max-per-lot", str(max_per_lot)])
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def write_dashboard_snapshot(lot: str | None = None, wafer: str | None = None) -> Path:
    """Write React-shaped dashboard JSON (all KPIs, ranking, tables)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dash = get_dashboard(mode="live", lot=lot, wafer=wafer)
    payload = dash.model_dump(mode="json")
    payload["exported_at"] = _utc_now()
    payload["export_kind"] = "dashboard_snapshot"
    path = OUTPUT_DIR / DASHBOARD_SNAPSHOT
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_export_manifest() -> Path:
    """Write KPI → requirement artifact index with dataset fingerprint."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures_df, load_src = load_failures(max_per_lot=None)
    logs = select_logs(max_per_lot=None)
    kpi_entries: list[dict[str, Any]] = []
    for row in KPI_ARTIFACT_MAP:
        artifact_path = OUTPUT_DIR / row["artifact"]
        kpi_entries.append({
            **row,
            "artifact_exists": artifact_path.exists(),
            "artifact_path": str(artifact_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        })
    manifest = {
        "generated_at": _utc_now(),
        "export_kind": "manifest",
        "dashboard_snapshot": DASHBOARD_SNAPSHOT,
        "dataset_fingerprint": {
            "log_file_count": len(logs),
            "failure_records": int(len(failures_df)),
            "load_source": load_src,
        },
        "kpis": kpi_entries,
        "requirement_artifacts": sorted(
            {p.name for p in OUTPUT_DIR.glob("SCD-FR-*") if p.is_file()}
        ),
    }
    path = OUTPUT_DIR / EXPORT_MANIFEST
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def export_all_agent_outputs(
    *,
    max_per_lot: int | None = None,
    lot: str | None = None,
    wafer: str | None = None,
    skip_requirement_cli: bool = False,
) -> dict[str, Any]:
    """
    Full agent export pipeline:
      - per-requirement JSON/HTML (export_outputs.py)
      - dashboard snapshot (React KPI shape)
      - manifest (KPI ↔ artifact map)
    """
    result: dict[str, Any] = {"generated_at": _utc_now(), "steps": {}}

    if not skip_requirement_cli:
        cli = run_requirement_exports(max_per_lot=max_per_lot)
        result["steps"]["requirement_exports"] = cli
        if not cli["ok"]:
            result["ok"] = False
            result["error"] = "export_outputs.py failed"
            return result

    dash_path = write_dashboard_snapshot(lot=lot, wafer=wafer)
    manifest_path = write_export_manifest()
    dash = get_dashboard(mode="live", lot=lot, wafer=wafer)

    result["ok"] = True
    result["steps"]["dashboard_snapshot"] = str(dash_path.relative_to(PROJECT_ROOT))
    result["steps"]["manifest"] = str(manifest_path.relative_to(PROJECT_ROOT))
    result["dataset_summary"] = dash.dataset_summary.model_dump()
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Export agent diagnosis outputs to output/")
    ap.add_argument("--max-per-lot", type=int, default=None, help="Limit logs per lot (default: all)")
    ap.add_argument("--snapshot-only", action="store_true", help="Skip FR exports; write dashboard + manifest only")
    args = ap.parse_args()
    out = export_all_agent_outputs(
        max_per_lot=args.max_per_lot,
        skip_requirement_cli=args.snapshot_only,
    )
    print(json.dumps(out, indent=2))
    raise SystemExit(0 if out.get("ok") else 1)
