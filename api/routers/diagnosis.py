"""Scan Diagnosis REST endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from api.adapters.agent_export import export_all_agent_outputs
from api.adapters.diagnosis_service import (
    copilot_answer,
    get_dashboard,
    get_kpi_workspace,
    report_html_path,
    REPORT_HTML_FILENAME,
    _DASHBOARD_CACHE,
    _logs_fingerprint,
    sync_review_queue,
)
from api.adapters.paths import PROJECT_ROOT, ensure_src_on_path
from api.models.schemas import (
    CopilotRequest,
    CopilotResponse,
    DiagnosisDashboard,
    HealthResponse,
    KpiWorkspace,
    ReviewActionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["scan-diagnosis"])


def _mode(explicit: Optional[str] = None) -> str:
    """Always use the live engine — decorative mock data was removed."""
    return "live"


@router.get("/health", response_model=HealthResponse)
def health(request: Request, mode: Optional[str] = Query(None)) -> HealthResponse:
    engine = False
    try:
        ensure_src_on_path()
        import chain_ranking  # noqa: F401

        engine = True
    except Exception:
        engine = False

    live_validation = getattr(request.app.state, "live_validation", None) or {}
    live_ok = bool(live_validation.get("ok", False))
    live_errors = list(live_validation.get("errors") or [])

    return HealthResponse(
        status="ok" if live_ok else "degraded",
        mode=_mode(mode),
        project_root=str(PROJECT_ROOT),
        engine_available=engine,
        live_path_ok=live_ok,
        failure_records=live_validation.get("failure_records"),  # type: ignore[arg-type]
        log_file_count=live_validation.get("log_file_count"),  # type: ignore[arg-type]
        live_errors=live_errors,
    )


@router.get("/diagnosis/dashboard", response_model=DiagnosisDashboard)
def diagnosis_dashboard(
    mode: Optional[str] = Query(None, description="live | mock"),
    lot: Optional[str] = Query(None),
    wafer: Optional[str] = Query(None),
    force: bool = Query(False, description="Bypass server cache and rebuild"),
) -> DiagnosisDashboard:
    try:
        return get_dashboard(mode=_mode(mode), lot=lot, wafer=wafer, force=force)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/kpi/{kpi_id}/workspace", response_model=KpiWorkspace)
def kpi_workspace(
    kpi_id: str,
    mode: Optional[str] = Query(None),
    min_observations: int = Query(2, ge=1, le=20, description="FR-002 min corroborating observations"),
) -> KpiWorkspace:
    try:
        return get_kpi_workspace(
            kpi_id=kpi_id,
            mode=_mode(mode),
            min_observations=min_observations,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/diagnosis/copilot", response_model=CopilotResponse)
def diagnosis_copilot(body: CopilotRequest, mode: Optional[str] = Query(None)) -> CopilotResponse:
    return copilot_answer(question=body.question, kpi_id=body.kpi_id, mode=_mode(mode))


@router.get("/diagnosis/filters")
def diagnosis_filters(mode: Optional[str] = Query(None)):
    dash = get_dashboard(mode=_mode(mode))
    return dash.filters


@router.get("/diagnosis/report/html")
def diagnosis_report_html(download: bool = Query(False, description="Force download attachment")):
    """Serve the FR-008 HTML report for preview (inline) or download."""
    path = report_html_path()
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "Report HTML not found. Run `python src/export_outputs.py` "
                f"({REPORT_HTML_FILENAME} under output/)."
            ),
        )
    disposition = "attachment" if download else "inline"
    mtime = int(path.stat().st_mtime)
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename=REPORT_HTML_FILENAME,
        headers={
            "Content-Disposition": f'{disposition}; filename="{REPORT_HTML_FILENAME}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "ETag": f'"{mtime}"',
        },
    )


@router.post("/diagnosis/export")
def diagnosis_export(
    lot: Optional[str] = Query(None),
    wafer: Optional[str] = Query(None),
    max_per_lot: Optional[int] = Query(None, description="Omit for full dataset; set e.g. 2 for quick subset"),
):
    """Regenerate per-requirement JSON + dashboard snapshot + KPI manifest under output/."""
    try:
        result = export_all_agent_outputs(max_per_lot=max_per_lot, lot=lot, wafer=wafer)
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result)
        _DASHBOARD_CACHE.clear()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/diagnosis/production/validation")
def production_validation():
    """Return cached/fresh lot-holdout + readiness metrics."""
    dash = get_dashboard(mode="live")
    return dash.production_validation or {}


@router.get("/diagnosis/reviews")
def list_reviews(
    limit: int = Query(50, ge=1, le=200),
    seed: bool = Query(True, description="Seed pending items when log fingerprint changed"),
):
    """Live review queue. Seeds new pending items when new logs arrive (fingerprint change)."""
    return sync_review_queue(seed_if_needed=seed, limit=limit)


@router.post("/diagnosis/reviews/{item_id}")
def review_item(item_id: str, body: ReviewActionRequest):
    ensure_src_on_path()
    from review_queue import submit_review
    from model_lifecycle import maybe_retrain, should_retrain

    try:
        result = submit_review(item_id, body.decision, reviewer_note=body.reviewer_note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Return immediately for lively UI. Only load failures when retrain is actually due.
    try:
        check = should_retrain()
        if check.get("due"):
            from api.adapters.data_loader import load_failures

            failures, _ = load_failures(max_per_lot=None)
            retrain = maybe_retrain(failures, force=False)
            result["retrain"] = {
                "retrained": retrain.get("retrained"),
                "reason": retrain.get("reason"),
                "feedback_count": retrain.get("feedback_count"),
            }
        else:
            result["retrain"] = {
                "retrained": False,
                "reason": "threshold_not_met",
                "feedback_count": check.get("feedback_count"),
                "due": False,
            }
    except Exception as exc:
        result["retrain"] = {"retrained": False, "reason": f"error:{exc}"}

    # Do NOT clear the heavy diagnosis cache — Pending Reviews KPI is overlaid live.
    return result


@router.post("/diagnosis/models/retrain")
def force_retrain():
    """Force GBM (+ RF) retrain from feedback + current failures."""
    ensure_src_on_path()
    from model_lifecycle import maybe_retrain
    from api.adapters.data_loader import load_failures

    try:
        failures, _ = load_failures(max_per_lot=None)
        result = maybe_retrain(failures, force=True)
        _DASHBOARD_CACHE.clear()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/diagnosis/production/fingerprint")
def data_fingerprint():
    return {"fingerprint": _logs_fingerprint()}
