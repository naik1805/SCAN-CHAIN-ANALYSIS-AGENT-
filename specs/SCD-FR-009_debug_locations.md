# Technical AI Agent Specification — SCD-FR-009

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-009) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Debug Location Recommendation Agent |
| **Requirement ID** | SCD-FR-009 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Debug Location Agent v1.0 |

---

## 2. Project Overview

**Objective:** Recommend physical PFA debug locations — die-local (x,y µm) and wafer (X,Y mm) coordinates for suspected cells, with priority scoring.

**Scope of this FR:** Coordinate computation + prioritized recommendation export (JSON + CSV).

**Stakeholders:** PFA engineers planning physical de-processing / probing.

---

## 3. Business Objective

**Problem:** Suspected cells are logical; PFA needs physical coordinates and a priority order.

**Expected outcome:** Ranked debug locations with local + wafer coordinates and supporting evidence.

**KPI:** `debug_locations` (AI section).

---

## 4. Technical Overview

**Workflow:** `locate_cells.locate_failing_cells(min_observations=1)` → **`debug_locations.calculate_cell_coordinates`** → `export_pfa_locations` (JSON + CSV).

**Technologies:** Serpentine placement model + hashlib micro-offsets; pandas.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, Recharts |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | Reuses FR-002/010 confidence + RF root cause |
| **Framework** | pandas, numpy, hashlib |
| **Database** | Parquet cache, JSON + CSV artifacts |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Compute die-local (x,y µm) coordinates via serpentine layout.
- Compute wafer (X,Y mm) coordinates per die occurrence.
- Score priority (High/Medium/Low) and export JSON + CSV.

**Exclusions:** Cell localization math (FR-002), report rendering (FR-008).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-009 |
| **Description** | Recommend PFA debug locations with die-local + wafer coordinates and priority scoring. |
| **Priority** | Medium |
| **Inputs** | Failure DataFrame + chain_map. Columns: `chain`, `fail_flop_id`, `cell_name`, `offset_from_scan_in`, `chain_length`, `bit_position`, `confidence`, `mean_ai_severity`, `predicted_root_cause`, `lot_id`, `die_label`, `x1`, `y1`. |
| **Outputs** | `SCD-FR-009_debug_locations.json` + `.csv` (see §11). |
| **Processing Logic** | Serpentine placement + priority (see §18). |
| **Dependencies** | FR-002 (`locate_failing_cells`), FR-010 confidence, RF root cause; numpy, pandas, hashlib. |

---

## 8. Non-Functional Requirements

- **Response time:** Sub-second to few seconds.
- **Scalability:** Thousands of recommendation rows (one per die occurrence in CSV).
- **Logging:** INFO; counts by priority.
- **Availability:** Deterministic (md5-seeded offsets).

---

## 9. AI Behavior Specification

- **Role:** Deterministic coordinate + priority recommender.
- **Workflow:** localize → place → prioritize → export.
- **Decision logic:** `priority_val = 0.5·confidence + 0.5·severity_val` → High≥0.55, Medium≥0.35, else Low; sort by priority then `-confidence`.
- **Limitations:** Coordinates are a modeled layout estimate, not GDS-exact.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Normalized schema. |
| `chain_map` | dict | Yes | For localization. |
| `x1`/`y1` | float | No | Wafer origin defaults 100.0 mm. |

---

## 11. Output Specification

**JSON** — `output/SCD-FR-009_debug_locations.json`. Top keys: `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `summary{total_recommended_cells, high_priority_count, medium_priority_count, low_priority_count}`, `recommendations[]`.

**`recommendations[]` item:** `cell_name`, `chain`, `fail_flop_id`, `logical_offset`, `local_coordinates{x_um, y_um}`, `confidence`, `predicted_root_cause`, `priority`, `distinct_dies_affected`, `supporting_evidence`, `die_occurrences[]` (`{lot_id, die_label, wafer_x_mm, wafer_y_mm}`).

**CSV** — `output/SCD-FR-009_debug_locations.csv` columns: `cell_name, chain, fail_flop_id, logical_offset, x_local_um, y_local_um, priority, confidence, predicted_root_cause, lot_id, die_label, wafer_x_mm, wafer_y_mm` (one row per die occurrence).

`calculate_cell_coordinates` DataFrame cols: `cell_name, chain, fail_flop_id, bit_position, offset_from_scan_in, x_local_um, y_local_um, confidence, predicted_root_cause, priority, occurrences, distinct_dies_affected`.

---

## 12. Business Rules

- **BR-001:** Layout: `die_h=die_w=4000µm`, `band_h=die_h/num_chains`, `rows_per_chain=5`, `cols=ceil(chain_len/5)`.
- **BR-002:** `cell_row=offset//cols`, `cell_col=offset%cols` (reversed on odd rows).
- **BR-003:** Micro-offsets from md5 (±3µm x, ±1µm y); clip to `[10, dim-10]`.
- **BR-004:** Wafer: `x_wafer = x1_mm + x_local/1000` (x1/y1 default 100.0).
- **BR-005:** Priority thresholds 0.55 / 0.35.

---

## 13. Key Engineering Rules

- Never claim GDS-exact coordinates — modeled layout, clearly documented.
- Deterministic (md5 seeding).
- Preserve terminology (die-local µm, wafer mm).

---

## 14. Constraints

- Die dims fixed at 4000µm; `rows_per_chain=5`.
- CSV one row per die occurrence (can be large).

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/debug_locations/workspace` |
| **Method** | GET |
| **Response** | Panels `debug_locations_panel` + `debug_locations_table` |
| **Errors** | Empty recommendations if no suspects. |

---

## 16. Database Design

- Parquet cache; artifacts `output/SCD-FR-009_debug_locations.json` + `.csv`.

---

## 17. Dashboard Integration

- **Screen:** AI section KPI `debug_locations`.
- **Action:** Drill-down → `DebugLocationsPanel.tsx`.
- **Outputs:** Ranked evidence cards + full coordinate table.

---

## 18. AI Workflow (Step-by-Step)

1. `locate_failing_cells(min_observations=1)` → suspects.
2. Serpentine placement per cell (`calculate_cell_coordinates`): rows/cols from chain length, reversed odd rows, md5 micro-offset, clip.
3. Wafer coords per die occurrence from `x1/y1` + local.
4. Priority = `0.5·confidence + 0.5·severity` → High/Medium/Low.
5. Sort by priority then `-confidence`.
6. `export_pfa_locations` → JSON + CSV.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| No suspects | No failures | Empty recommendations. |
| Missing die coords | Log gap | Default wafer origin 100.0. |
| Divide by zero | `num_chains=0` | Guard; skip placement. |

---

## 20. Logging & Monitoring

- **Logs:** priority counts.
- **Metrics:** `total_recommended_cells`, priority breakdown.
- **Alerts:** N/A.

---

## 21. Security

- No auth; local data only.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-009-01 | FR-009 | Coordinates for known cell | x/y within die bounds | Pass |
| TC-009-02 | FR-009 | Priority scoring | Correct High/Medium/Low | Pass |
| TC-009-03 | FR-009 | CSV export | One row per die occurrence | Pass |

---

## 23. Acceptance Criteria

- Coordinates within `[10, 3990]µm`; wafer coords computed per die.
- Priority thresholds applied; sorted correctly.
- JSON + CSV both exported with defined columns.

---

## 24. Risks & Assumptions

- **Risk:** Coordinates mistaken for GDS-exact; mitigation: documented as modeled.
- **Assumption:** Serpentine model adequately guides physical probing.

---

## 25. Dependencies

- Internal: FR-002 localization, FR-010 confidence, RF root cause, `debug_locations`.
- External: numpy, pandas, hashlib.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-009 | `debug_locations.calculate_cell_coordinates`, `export_pfa_locations` | `SCD-FR-009_debug_locations.json` / `.csv` | TC-009-01..03 | §23 |

---

## 27. Reviewer Checklist

- [ ] Coordinates within bounds + deterministic.
- [ ] Priority logic correct.
- [ ] JSON + CSV columns match spec.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| PFA Engineering | | |
