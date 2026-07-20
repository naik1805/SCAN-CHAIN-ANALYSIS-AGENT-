# Technical AI Agent Specification — SCD-FR-006

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-006) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Scan Chain Break Localization Agent |
| **Requirement ID** | SCD-FR-006 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Chain Break Agent v1.0 |

---

## 2. Project Overview

**Objective:** Detect scan-chain breaks and localize the exact break bit via per-pattern first-mismatch consensus, gated by a CERTAIN/UNCERTAIN production-honesty rule.

**Scope of this FR:** Break detection + exact-bit localization with confidence and honest status.

**Stakeholders:** DFT / PFA engineers diagnosing hard scan-path opens.

---

## 3. Business Objective

**Problem:** A broken chain blocks all downstream cells; engineers need the exact break location — but only when evidence supports it.

**Expected outcome:** Break list with candidate/exact bit, cell, and a CERTAIN/UNCERTAIN status that never over-claims.

**KPI:** `chain_breaks` (overview section).

---

## 4. Technical Overview

**Workflow:** parse → normalize → enrich positions → **`chain_breaks.detect_chain_breaks_detailed`** → `export_outputs.build_fr006` → JSON.

**Technologies:** Trailing-X care-bit trimming, per-pattern first-mismatch consensus, ±5-bit soft agreement.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, Recharts |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | None (deterministic consensus) |
| **Framework** | pandas, numpy |
| **Database** | Parquet cache, JSON artifacts |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Trim trailing-X care bits; apply break gate.
- Compute exact break bit via first-mismatch mode/median.
- Score soft agreement (±5 bits); set CERTAIN/UNCERTAIN.
- Emit candidate/exact bit + cell, upstream/downstream cells, bitstreams.

**Exclusions:** Cell confidence (FR-002/010), shift/capture classification (FR-007).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-006 |
| **Description** | Localize exact scan-chain break bit via per-pattern first-mismatch consensus, gated by CERTAIN/UNCERTAIN honesty rule. |
| **Priority** | High |
| **Inputs** | Failure DataFrame + chain_map. Columns: `bit_position`, `chain_length`, `expected_output`, `actual_output`, `pattern_id`, `chain`, `chain_id`, `lot_id`, `source_file`, `fail_flop_id`. |
| **Outputs** | `SCD-FR-006_scan_chain_breaks.json` (see §11). |
| **Processing Logic** | Trailing-X gate + consensus + soft agreement (see §18). |
| **Dependencies** | FR-001 pipeline, FR-003 chain_map, `locate_cells`; numpy, pandas. Config `break_min_unique_positions=5`. |

---

## 8. Non-Functional Requirements

- **Response time:** Few seconds across grouped patterns.
- **Scalability:** Per `(source_file, lot_id, chain)` grouping.
- **Logging:** INFO; certain/uncertain counts.
- **Availability:** Deterministic; honest defaults when uncertain.

---

## 9. AI Behavior Specification

- **Role:** Deterministic break localizer with honesty gate.
- **Workflow:** trim → gate → consensus → confidence → status.
- **Decision logic:** exact bit = mode of first-mismatch (`agreement≥0.5`), else median (`patterns≥3`), else min; `location_confidence = soft_agreement` (fraction within ±5 bits); `CERTAIN` iff `soft_agreement≥0.70 AND patterns_total≥2`, else `UNCERTAIN` (exact fields nulled).
- **Limitations:** Never reports exact bit unless CERTAIN — avoids false precision.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Needs `expected_output`/`actual_output` bitstreams. |
| `chain_map` | dict | Yes | For cell naming (`_cell_at_bit`, `resolve_chain`). |
| `break_min_unique_positions` | int | No | `config.diagnosis=5`. |

---

## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-006_scan_chain_breaks.json`.

**Top keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `localization{method:"per_pattern_first_mismatch_consensus", description, certain_soft_agreement_min:0.70, certain_min_patterns:2}`, `inputs{logs_parsed, total_fail_records, stil_file}`, `summary{total_detected_breaks, location_certain_count, location_uncertain_count, unique_lots_affected, unique_dice_affected, mean_location_confidence, exact_locations_reported}`, `breaks[]`.

**`breaks[]` item:** `source_file`, `lot_id`, `chain`, `chain_id`, `chain_length`, `candidate_break_bit_position`, `candidate_break_cell`, `break_bit_position`, `exact_break_bit_position` (None unless CERTAIN), `exact_break_cell` (`LOCATION_UNCERTAIN` unless CERTAIN), `suspected_break_cell`, `location_status`, `location_status_reason`, `offset_from_scan_in`, `downstream_cell_toward_so`, `upstream_cell_toward_si`, `location_confidence`, `exact_agreement`, `soft_agreement`, `first_mismatch_std`, `confidence_definition`, `localization_method`, `patterns_agreeing`, `patterns_agreeing_exact`, `patterns_analyzed`, `upstream_coverage`, `downstream_fail_fraction`, `fail_count`, `unique_failing_positions`, `scan_in`, `scan_out`, `expected_actual_bitstreams[]`.

---

## 12. Business Rules

- **BR-001:** `max_care` = last non-`X` index of expected bitstream (trailing-X trim).
- **BR-002:** Break gate: `min_pos>0 AND max_pos>=(max_care-5) AND unique_pos>=5 AND patterns>=1 AND downstream_fail_fraction<=0.15`.
- **BR-003:** `location_confidence = soft_agreement` (±5-bit fraction).
- **BR-004:** `CERTAIN` iff `soft_agreement>=0.70 AND patterns_total>=2`; else `UNCERTAIN`, exact fields nulled.

---

## 13. Key Engineering Rules

- Never over-claim exact break — honesty gate is mandatory (no artificial floor).
- Preserve terminology (upstream toward SI, downstream toward SO).
- Deterministic consensus.

---

## 14. Constraints

- `certain_soft_agreement_min=0.70`, `certain_min_patterns=2`.
- `break_min_unique_positions=5`; downstream fail fraction ≤ 0.15.
- Chain-length fallback `234`.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/chain_breaks/workspace` |
| **Method** | GET |
| **Response** | Panel kind `break_visualizer` |
| **Errors** | Empty breaks when gate not met. |

---

## 16. Database Design

- Parquet cache; artifact `output/SCD-FR-006_scan_chain_breaks.json`.

---

## 17. Dashboard Integration

- **Screen:** Overview KPI `chain_breaks`.
- **Action:** Drill-down → `ScanChainBreakVisualizer.tsx` (+ `lib/scanChainBreak/buildBreakSchematic.ts`).
- **Outputs:** Break schematic with red break FF, upstream/downstream, CERTAIN/UNCERTAIN badge.

---

## 18. AI Workflow (Step-by-Step)

1. Group by `(source_file, lot_id, chain)`.
2. Trailing-X trim → `max_care`.
3. Apply break gate (BR-002).
4. Per-pattern first mismatch → exact bit (mode/median/min).
5. `soft_agreement` = fraction within ±5 bits; `exact_agreement` = exact-bit fraction.
6. Set `location_status` (CERTAIN/UNCERTAIN) + reason; null exact fields if UNCERTAIN.
7. Map bits → cells (`_cell_at_bit`); attach upstream/downstream + bitstreams.
8. Assemble summary + serialize.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Gate not met | Point defects / few patterns | No break reported. |
| Low agreement | Patterns disagree | `UNCERTAIN`, exact nulled. |
| Missing bitstream | Parser gap | Skip group, log warning. |

---

## 20. Logging & Monitoring

- **Logs:** certain/uncertain counts.
- **Metrics:** `mean_location_confidence`, `exact_locations_reported`.
- **Alerts:** N/A.

---

## 21. Security

- No auth; local data only.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-006-01 | FR-006 | Synthetic break, agreeing patterns | `CERTAIN`, exact bit set | Pass |
| TC-006-02 | FR-006 | Disagreeing patterns | `UNCERTAIN`, exact nulled | Pass |
| TC-006-03 | FR-006 | Point defect | No break (gate fails) | Pass |

---

## 23. Acceptance Criteria

- Break gate filters point defects.
- Exact bit only when CERTAIN.
- `location_confidence` = soft agreement; status reason present.

---

## 24. Risks & Assumptions

- **Risk:** Over-claiming exact location; mitigation: honesty gate + tests.
- **Assumption:** First mismatch approximates break site.

---

## 25. Dependencies

- Internal: FR-001 pipeline, FR-003 chain_map, `chain_breaks`, `locate_cells`.
- External: numpy, pandas.
- Consumed by: FR-007 (shift issue), FR-008 (report).

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-006 | `chain_breaks.detect_chain_breaks_detailed`, `export_outputs.build_fr006` | `SCD-FR-006_scan_chain_breaks.json` | TC-006-01..03 | §23 |

---

## 27. Reviewer Checklist

- [ ] Trailing-X trim correct.
- [ ] Gate filters point defects.
- [ ] CERTAIN/UNCERTAIN thresholds enforced.
- [ ] Exact fields nulled when uncertain.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| PFA Engineering | | |
