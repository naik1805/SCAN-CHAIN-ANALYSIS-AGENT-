# Technical AI Agent Specification — SCD-FR-007

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-007) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Shift vs Capture Diagnosis Agent |
| **Requirement ID** | SCD-FR-007 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Shift/Capture Diagnosis Agent v1.0 |

---

## 2. Project Overview

**Objective:** Classify each failure as a shift-path break vs capture-timing (setup/hold, with anomaly variants) vs capture cell defect.

**Scope of this FR:** Per-failure classification cascade using break signature + slack signs + anomaly flag.

**Stakeholders:** DFT engineers separating shift vs capture root causes.

---

## 3. Business Objective

**Problem:** A failure can stem from the shift path or capture timing; treatment differs greatly.

**Expected outcome:** Every failure labeled into an actionable class with supporting details.

**KPI:** `shift_capture` (overview section).

---

## 4. Technical Overview

**Workflow:** parse → normalize → ML enrich (anomaly + RF) → position enrich → **`export_outputs.build_fr007`** (reuses FR-006 break gate) → JSON.

**Technologies:** Deterministic decision cascade; IsolationForest anomaly flag; RandomForest root cause for defect details.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, Recharts |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | scikit-learn (IsolationForest `contamination=0.05`, RandomForest) |
| **Framework** | pandas, numpy |
| **Database** | Parquet cache, JSON artifacts, model store |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Recompute broken chains (FR-006 gate) to flag shift issues.
- Classify capture-timing setup/hold using slack signs + anomaly flag.
- Fall back to capture cell defect with RF root cause detail.

**Exclusions:** Exact break bit (FR-006), cell confidence (FR-002/010).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-007 |
| **Description** | Classify each failure into shift vs capture-timing vs cell-defect categories. |
| **Priority** | Medium-High |
| **Inputs** | Enriched failure DataFrame + chain_map. Columns: `source_file`, `lot_id`, `chain`, `bit_position`, `chain_length`, `expected_output`, `setup_slack_ps`, `hold_slack_ps`, `is_anomaly`, `predicted_root_cause`, `pattern_id`, `fail_flop_id`. |
| **Outputs** | `SCD-FR-007_shift_capture_diagnosis.json` (see §11). |
| **Processing Logic** | FR-006 break gate + slack decision cascade (see §18). |
| **Dependencies** | FR-006 break logic, FR-002 enrichment, `ml_pipeline` (IsolationForest, RF). |

---

## 8. Non-Functional Requirements

- **Response time:** Few seconds across all failures.
- **Scalability:** Row-level classification over full failure set.
- **Logging:** INFO; class histogram.
- **Availability:** Deterministic; anomaly/RF enrich shared pipeline.

---

## 9. AI Behavior Specification

- **Role:** Deterministic classifier with ML-assisted anomaly/root-cause detail.
- **Workflow:** break-set membership → slack sign cascade → anomaly variant → defect fallback.
- **Decision logic:** see §18 cascade.
- **Limitations:** Timing classes depend on slack sign accuracy in logs.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Must carry `setup_slack_ps`, `hold_slack_ps`, `is_anomaly`. |
| `chain_map` | dict | Yes | For position enrichment. |

---

## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-007_shift_capture_diagnosis.json`.

**Top keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `inputs{logs_parsed, total_fail_records, stil_file}`, `summary{total_diagnoses, shift_issues, capture_timing_setup, capture_timing_setup_anomaly, capture_timing_hold, capture_timing_hold_anomaly, capture_cell_defect}`, `diagnoses[]`.

**`diagnoses[]` item:** `lot_id`, `source_file`, `pattern_id`, `chain`, `flop_id`, `bit_position`, `classification`, `details`.

**Classes:** `SHIFT_ISSUE`, `CAPTURE_TIMING_SETUP`, `CAPTURE_TIMING_SETUP_ANOMALY`, `CAPTURE_TIMING_HOLD`, `CAPTURE_TIMING_HOLD_ANOMALY`, `CAPTURE_CELL_DEFECT`.

---

## 12. Business Rules

- **BR-001:** In broken chain (FR-006 gate) ⇒ `SHIFT_ISSUE`.
- **BR-002:** `setup_slack<0 AND setup_slack<=hold_slack` ⇒ `CAPTURE_TIMING_SETUP` (+`_ANOMALY` if `is_anomaly`).
- **BR-003:** `hold_slack<0 AND hold_slack<setup_slack` ⇒ `CAPTURE_TIMING_HOLD` (+`_ANOMALY` if `is_anomaly`).
- **BR-004:** else ⇒ `CAPTURE_CELL_DEFECT` (details include RF `predicted_root_cause`).
- **BR-005:** Sorted by `(lot_id, source_file, pattern_id, chain)`.

---

## 13. Key Engineering Rules

- Never label without evidence — cascade is explicit and ordered.
- Preserve terminology (shift vs capture, setup/hold).
- Deterministic; anomaly flag from `contamination=0.05`.

---

## 14. Constraints

- Break gate identical to FR-006 (trailing-X, `unique_pos>=5`, etc.).
- Requires slack columns; else defaults toward defect class.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/shift_capture/workspace` |
| **Method** | GET |
| **Response** | Panel kind `shift_capture` |
| **Errors** | Empty diagnoses if no failures. |

---

## 16. Database Design

- Parquet cache + model store; artifact `output/SCD-FR-007_shift_capture_diagnosis.json`.

---

## 17. Dashboard Integration

- **Screen:** Overview KPI `shift_capture`.
- **Action:** Drill-down → `ShiftCaptureChart.tsx`.
- **Outputs:** Classification donut + per-class registry.

---

## 18. AI Workflow (Step-by-Step)

1. Enrich positions + ML (`is_anomaly`, `predicted_root_cause`).
2. Recompute broken chains with FR-006 gate.
3. Per row cascade:
   - broken chain ⇒ `SHIFT_ISSUE`;
   - elif `setup_slack<0 and setup_slack<=hold_slack` ⇒ `CAPTURE_TIMING_SETUP[_ANOMALY]`;
   - elif `hold_slack<0 and hold_slack<setup_slack` ⇒ `CAPTURE_TIMING_HOLD[_ANOMALY]`;
   - else ⇒ `CAPTURE_CELL_DEFECT` (RF detail).
4. Tally summary; sort; serialize.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Missing slack | Column absent | Route to defect class. |
| No anomaly model | Missing model | `is_anomaly=False`, no anomaly variant. |

---

## 20. Logging & Monitoring

- **Logs:** class histogram.
- **Metrics:** per-class counts in `summary`.
- **Alerts:** N/A.

---

## 21. Security

- No auth; local data only.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-007-01 | FR-007 | Broken chain row | `SHIFT_ISSUE` | Pass |
| TC-007-02 | FR-007 | `setup_slack<0` | `CAPTURE_TIMING_SETUP` | Pass |
| TC-007-03 | FR-007 | anomaly + setup | `CAPTURE_TIMING_SETUP_ANOMALY` | Pass |
| TC-007-04 | FR-007 | positive slacks | `CAPTURE_CELL_DEFECT` | Pass |

---

## 23. Acceptance Criteria

- Every failure receives exactly one class.
- Summary counts sum to `total_diagnoses`.
- Anomaly variants applied only when `is_anomaly`.

---

## 24. Risks & Assumptions

- **Risk:** Noisy slack values misclassify; mitigation: ordered cascade + anomaly flag.
- **Assumption:** Slack signs reflect true timing margin.

---

## 25. Dependencies

- Internal: FR-006 break gate, FR-002 enrichment, `ml_pipeline`.
- External: scikit-learn, numpy, pandas.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-007 | `export_outputs.build_fr007` (+ FR-006 gate, `ml_pipeline`) | `SCD-FR-007_shift_capture_diagnosis.json` | TC-007-01..04 | §23 |

---

## 27. Reviewer Checklist

- [ ] Cascade order correct.
- [ ] Anomaly variants gated by `is_anomaly`.
- [ ] Counts sum correctly.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| Test Engineering | | |
