"""Pydantic response models for the Scan Diagnosis API shell."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SparkPoint(BaseModel):
    x: str
    y: float


class KpiCard(BaseModel):
    id: str
    section: Literal["overview", "engineering", "ai"]
    label: str
    value: str | int | float
    unit: Optional[str] = None
    trend_pct: Optional[float] = None
    badge: Optional[str] = None
    badge_tone: Literal["danger", "success", "warning", "info", "neutral"] = "neutral"
    status: Literal["ok", "empty", "na", "error"] = "ok"
    caption: Optional[str] = None
    sparkline: list[SparkPoint] = Field(default_factory=list)
    help: Optional[str] = None


class FilterOptions(BaseModel):
    lots: list[str] = Field(default_factory=list)
    wafers: list[str] = Field(default_factory=list)
    testers: list[str] = Field(default_factory=list)
    fabs: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)


class DatasetSummary(BaseModel):
    """Active STIL/logs and FAIL population counts for the filter strip."""

    stil_file: str = "—"
    log_files: list[str] = Field(default_factory=list)
    log_file_count: int = 0
    total_failure_records: int = 0
    failing_chains: int = 0
    all_chains: int = 0
    failing_flops: int = 0


class MlStatusSummary(BaseModel):
    """Client-readable status of ML models on the active failure dataset."""

    active: bool = False
    failure_records_analyzed: int = 0
    root_cause_model: str = "Random Forest"
    anomaly_model: str = "Isolation Forest"
    confidence_model: str = "Gradient Boosting (verified history)"
    root_causes_estimated: int = 0
    anomaly_flagged_count: int = 0
    anomaly_flagged_pct: float = 0.0
    client_summary: str = "AI models are ready — load failure logs to run analysis."


class ChartSeries(BaseModel):
    name: str
    points: list[dict[str, Any]] = Field(default_factory=list)


class DiagnosisDashboard(BaseModel):
    title: str = "Scan Diagnosis"
    subtitle: str = (
        "Real-time diagnosis of scan chain failures using topology analysis, "
        "AI root cause detection and engineering recommendations."
    )
    data_source: Literal["fastapi-live", "fastapi-exports", "mock"]
    mode: Literal["live", "mock"]
    filters: FilterOptions
    dataset_summary: DatasetSummary = Field(default_factory=DatasetSummary)
    ml_status: MlStatusSummary = Field(default_factory=MlStatusSummary)
    production_validation: dict[str, Any] = Field(default_factory=dict)
    kpis: list[KpiCard]
    ranking: list[dict[str, Any]] = Field(default_factory=list)
    correlations: list[dict[str, Any]] = Field(default_factory=list)
    shift_capture: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, Any] = Field(default_factory=dict)
    topology_summary: dict[str, Any] = Field(default_factory=dict)
    breaks_table: list[dict[str, Any]] = Field(default_factory=list)
    cells_table: list[dict[str, Any]] = Field(default_factory=list)
    reports_meta: dict[str, Any] = Field(default_factory=dict)
    footer: str = "Data source: FastAPI"


class WorkspacePanel(BaseModel):
    kind: str
    title: str
    description: Optional[str] = None
    table: list[dict[str, Any]] = Field(default_factory=list)
    chart: Optional[dict[str, Any]] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class KpiWorkspace(BaseModel):
    kpi_id: str
    title: str
    status: Literal["ok", "empty", "na", "error"] = "ok"
    summary: dict[str, Any] = Field(default_factory=dict)
    panels: list[WorkspacePanel] = Field(default_factory=list)
    data_source: str = "fastapi-live"
    message: Optional[str] = None


class CopilotRequest(BaseModel):
    question: str
    kpi_id: Optional[str] = None


class CopilotResponse(BaseModel):
    answer: str
    citations: list[str] = Field(default_factory=list)
    data_source: str = "fastapi-live"


class ReviewActionRequest(BaseModel):
    decision: Literal["confirm", "reject", "defer"]
    reviewer_note: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    mode: str
    project_root: str
    engine_available: bool
    live_path_ok: bool = True
    failure_records: Optional[int] = None
    log_file_count: Optional[int] = None
    live_errors: list[str] = Field(default_factory=list)
