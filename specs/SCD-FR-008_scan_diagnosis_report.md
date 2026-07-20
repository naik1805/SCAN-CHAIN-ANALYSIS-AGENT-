# Technical AI Agent Specification — SCD-FR-008

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-008) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Scan Diagnosis Report Generation Agent |
| **Requirement ID** | SCD-FR-008 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Diagnosis Report Agent v1.0 |

---

## 2. Project Overview

**Objective:** Produce a single self-contained, print-ready HTML diagnosis report aggregating FR-001…FR-007 + FR-009, with inline SVG charts.

**Scope of this FR:** Report assembly and rendering; no new analysis math beyond reusing other FR modules.

**Stakeholders:** DFT / PFA engineers, management (shareable artifact).

---

## 3. Business Objective

**Problem:** Engineers need one shareable document summarizing the full diagnosis, not a dozen JSON files.

**Expected outcome:** A standalone HTML report (no external assets) covering all findings.

**KPI:** `diagnosis_reports` (AI section).

---

## 4. Technical Overview

**Workflow:** `diagnosis_context.build_diagnosis_bundle` → **`report_generator.generate_html_report`** (+ inline SVG donut/bar) → HTML file; served via API.

**Technologies:** Pure-Python HTML/SVG generation (no JS chart deps server-side).

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15 panel embeds/links the HTML; report itself is self-contained HTML+SVG |
| **Backend** | FastAPI (`report/html` route), Uvicorn |
| **LLM / ML** | Reuses FR-002/010 confidence + RF (via bundled analyses) |
| **Framework** | pandas, math (SVG geometry) |
| **Database** | Reads engine outputs; writes HTML artifact |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Build the diagnosis bundle (topology + all FR analyses).
- Render executive summary + 9 sections with tables and inline SVG charts.
- Enforce CERTAIN-only display of exact break bit/cell.

**Exclusions:** New analysis algorithms (delegated to FR-001…007, FR-009).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-008 |
| **Description** | Generate a self-contained interactive/print HTML report aggregating all diagnosis findings. |
| **Priority** | Medium |
| **Inputs** | Failure DataFrame, chain_map, `output_path`, `log_dir`, `project_root`. |
| **Outputs** | `SCD-FR-008_scan_diagnosis_report.html` (see §11). |
| **Processing Logic** | Bundle build → section render → SVG charts (see §18). |
| **Dependencies** | FR-001…007 + FR-009 modules, `diagnosis_context`; pandas, math. |

---

## 8. Non-Functional Requirements

- **Response time:** Few seconds (re-runs analyses once).
- **Scalability:** Single-file output regardless of dataset size (tables paginated in UI).
- **Logging:** INFO; raises `ValueError` on empty df.
- **Availability:** Served inline or as download via API.

---

## 9. AI Behavior Specification

- **Role:** Deterministic aggregator/renderer.
- **Workflow:** gather → render sections → embed SVG.
- **Decision logic:** break table shows exact bit/cell only if `location_status=="CERTAIN"`, else `LOCATION_UNCERTAIN` / `—`.
- **Limitations:** Presentation only; correctness inherited from source FRs.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Non-empty (else `ValueError`). |
| `chain_map` | dict | Yes | Topology for section 3. |
| `output_path` | Path | Yes | Writable HTML target. |
| `log_dir`, `project_root` | Path | Yes | For metadata + relative resolution. |

---

## 11. Output Specification

**Format:** Self-contained HTML (inline CSS + SVG). **File:** `output/SCD-FR-008_scan_diagnosis_report.html`.

**Sections:**
1. Executive Summary (FAIL records, failing chains, detected breaks, affected dice, active STIL, lots)
2. Failing Chains (FR-001)
3. Topology Map (FR-003)
4. Scan Chain Breaks (FR-006, CERTAIN/UNCERTAIN table)
5. Pareto Ranking (FR-004)
6. Suspected Cells (FR-002)
7. Failure Correlation (FR-005 Pearson matrix + driver breakdown)
8. Shift vs Capture (FR-007 donut + registry)
9. Debug Locations (FR-009)

Written via `output_path.write_text(html)`.

---

## 12. Business Rules

- **BR-001:** SVG donut from FR-007 `class_counts`; horizontal bar from ranked chains.
- **BR-002:** Exact break bit/cell displayed only when CERTAIN.
- **BR-003:** Empty DataFrame ⇒ `ValueError` (no empty report).

---

## 13. Key Engineering Rules

- Never present uncertain results as certain.
- Self-contained output (no external asset dependencies).
- Preserve terminology + section numbering.

---

## 14. Constraints

- Single HTML file; inline SVG only.
- Report filename fixed: `SCD-FR-008_scan_diagnosis_report.html`.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/diagnosis/report/html?download=` |
| **Method** | GET |
| **Response** | `text/html` (inline or attachment) |
| **Errors** | 404/500 if report cannot be generated; empty df ⇒ ValueError upstream. |

---

## 16. Database Design

- Reads engine analyses; writes HTML artifact to `output/`.

---

## 17. Dashboard Integration

- **Screen:** AI section KPI `diagnosis_reports`.
- **Action:** Drill-down → `DiagnosisReportPanel.tsx` (panel kind `reports`); open/download HTML.
- **Outputs:** Embedded/linked report.

---

## 18. AI Workflow (Step-by-Step)

1. `build_diagnosis_bundle` → topology + failing chain sets.
2. Re-run FR analyses (ranking, breaks, cells, correlation, shift/capture, debug locations).
3. Render executive summary.
4. Render sections 2–9 with tables; `generate_svg_donut` (classification), `generate_svg_bar` (worst chains).
5. Enforce CERTAIN-only exact break display.
6. `output_path.write_text(html)`.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Empty df | No failures | Raise `ValueError`. |
| Missing section data | Analysis empty | Render placeholder/empty section. |
| Write failure | Permissions | Log error, surface via API 500. |

---

## 20. Logging & Monitoring

- **Logs:** report path, section counts.
- **Metrics:** breaks/chains/cells embedded.
- **Alerts:** N/A.

---

## 21. Security

- No auth. Report contains internal test data; keep on local/volume storage.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-008-01 | FR-008 | Generate on fixture | HTML with all 9 sections | Pass |
| TC-008-02 | FR-008 | Empty df | `ValueError` raised | Pass |
| TC-008-03 | FR-008 | Uncertain break | Shows `LOCATION_UNCERTAIN` | Pass |

---

## 23. Acceptance Criteria

- Report is self-contained and opens without external assets.
- All 9 sections present with correct figures.
- Exact break only when CERTAIN.

---

## 24. Risks & Assumptions

- **Risk:** Large tables bloat HTML; mitigation: summarize/cap in report, full data in JSON.
- **Assumption:** Source FR analyses are correct.

---

## 25. Dependencies

- Internal: FR-001…007 + FR-009 modules, `diagnosis_context`, `report_generator`.
- External: pandas, math.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-008 | `report_generator.generate_html_report`, `diagnosis_context.build_diagnosis_bundle` | `SCD-FR-008_scan_diagnosis_report.html` | TC-008-01..03 | §23 |

---

## 27. Reviewer Checklist

- [ ] All 9 sections render.
- [ ] Self-contained (inline SVG/CSS).
- [ ] CERTAIN-only exact break.
- [ ] Empty-data path raises.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| Management | | |
