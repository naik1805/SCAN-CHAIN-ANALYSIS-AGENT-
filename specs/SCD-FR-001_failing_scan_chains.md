# Technical AI Agent Specification — SCD-FR-001

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-001) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information


| Field              | Value                                        |
| ------------------ | -------------------------------------------- |
| **Project**        | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name**     | Failing Scan Chain Identification Agent      |
| **Requirement ID** | SCD-FR-001                                   |
| **Version**        | v1.0                                         |
| **Author**         | Diagnosis Engineering                        |
| **Reviewer**       | DFT Lead                                     |
| **Date**           | 2026-07-18                                   |
| **Example**        | Failing Scan Chain Agent v1.0                |


---



## 2. Project Overview

**Objective:** Ingest Automatic Test Equipment (ATE) pattern logs (Tessent + compact inline multi-channel formats), compare against design STIL structure, and produce validated per-requirement JSON reports plus an interactive Next.js dashboard.

**Scope of this FR:** Identify every scan chain that produced at least one FAIL record, and quantify its failure footprint (counts, distinct patterns/flops, lots affected, fail-type breakdown, Pareto rank).

**Stakeholders:** DFT engineers, failure-analysis (PFA) engineers, yield/product engineers.

---



## 3. Business Objective

**Problem:** When thousands of FAIL records span dozens of scan chains, engineers cannot manually tell which chains are actually failing or how badly.

**Expected outcome:** A ranked, deterministic list of failing chains that immediately shows where to focus debug effort.

**KPI:** `failing_chains` — distinct count of failing scan chains (dashboard overview tile).

---



## 4. Technical Overview

**Architecture:** Python engine (`src/`) → FastAPI adapters (`api/`) → Next.js dashboard (`frontend/`).

**Workflow:** `parser.parse_log_to_dataframe` → `schema.normalize_failure_schema` → `ml_pipeline.apply_failure_ml` → `export_outputs.build_fr001` → JSON artifact + KPI workspace.

**Technologies:** pandas (vectorized groupby), `concurrent.futures.ProcessPoolExecutor` ingestion, Parquet warm cache (`disk_cache`).

---



## 5. Technology Stack


| Layer          | Technology                                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| **Frontend**   | Next.js 15 (app router), React 19, TypeScript 5.7, TailwindCSS 3.4, Recharts, framer-motion, @tanstack/react-query |
| **Backend**    | FastAPI ≥0.115, Uvicorn, Pydantic v2                                                                               |
| **LLM / ML**   | scikit-learn ≥1.5 (RandomForest root cause, IsolationForest anomaly) — not required for FR-001 core                |
| **Framework**  | pandas ≥2.2, numpy ≥1.26, pyarrow ≥16                                                                              |
| **Database**   | File-based: Parquet cache (`data/cache/`), JSON artifacts (`output/`)                                              |
| **IDE**        | VS Code / Cursor                                                                                                   |
| **Deployment** | Docker + docker-compose (API), local `npm run dev` (UI)                                                            |


---



## 6. Agent Responsibilities

**Responsibilities:**

- Aggregate FAIL records by `chain`.
- Compute fail count, fail %, distinct patterns, distinct fail flops, lots affected, fail-type breakdown.
- Rank chains by fail count (descending) and emit a schema-stable JSON report.

**Exclusions:**

- Does NOT localize cells (FR-002), detect breaks (FR-006), or rank with Pareto cumulative coverage as a first-class output (that is FR-004).

---



## 7. Functional Requirements


| Field                | Value                                                                                                                                                            |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **FR ID**            | SCD-FR-001                                                                                                                                                       |
| **Description**      | Identify failing scan chains and quantify each chain's failure footprint from parsed ATE FAIL records.                                                           |
| **Priority**         | High (foundational — all other FRs consume the same parsed failure set)                                                                                          |
| **Inputs**           | Failure DataFrame (all parsed FAIL records); list of log file paths. Columns consumed: `chain`, `fail_type`, `pattern_id`, `fail_flop_id`, `lot_id`, `chain_id`. |
| **Outputs**          | `SCD-FR-001_failing_scan_chains.json` (see §11).                                                                                                                 |
| **Processing Logic** | `groupby("chain")` → per-chain aggregates → sort by `fail_count` desc → assign `rank`. (see §18)                                                                 |
| **Dependencies**     | `parser`, `schema`, `disk_cache`, `ml_pipeline` (enrichment), pandas.                                                                                            |


---



## 8. Non-Functional Requirements

- **Response time:** Warm-cache dashboard build < 0.2 s cache load; full 90-log parse ≈ 10 s (parallel).
- **Scalability:** Handles 90+ logs / 5,000+ FAIL records; ProcessPoolExecutor ingestion.
- **Logging:** Rotating file logs under `output/run_logs/` (5 MB × 5 backups, INFO level).
- **Availability:** Stateless API; deterministic recompute from logs.

---



## 9. AI Behavior Specification

- **Role:** Deterministic aggregator (no generative behavior in FR-001).
- **Workflow:** Parse → normalize → aggregate → rank → serialize.
- **Decision logic:** Pure pandas aggregation; no thresholds beyond "≥1 FAIL record => failing chain".
- **Limitations:** Output reflects only records present in the loaded logs; a chain with zero FAIL records is never reported.

---



## 10. Input Specification


| Name                    | Type             | Required | Validation                                                                                                                 |
| ----------------------- | ---------------- | -------- | -------------------------------------------------------------------------------------------------------------------------- |
| `failures_df`           | pandas.DataFrame | Yes      | Passes `schema.normalize_failure_schema`; required cols `{lot_id, source_file, chain_id, chain, fail_flop_id, fail_type}`. |
| `paths`                 | list[Path]       | Yes      | Discovered via `parser.discover_logs`; each an existing ATE log file.                                                      |
| `lot` / `wafer` filters | string           | No       | Optional dashboard filters passed to API.                                                                                  |


Parser contract: one FAIL record is emitted per mismatching bit (EXPECTED_OUTPUT vs ACTUAL_OUTPUT, ignoring `X`), tagged `FAIL_FLOP_ID=FF_{bit+1}`, `FAIL_TYPE=SCAN_SHIFT`.

---



## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-001_failing_scan_chains.json`.

**Top-level keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `inputs{logs_parsed, log_files, lots}`, `summary{total_fail_records, distinct_failing_chains, distinct_failing_flops}`, `failing_chains[]`.

`failing_chains[]` **item:**

```json
{
  "chain": "channel01",
  "fail_count": 812,
  "fail_pct": 15.96,
  "distinct_patterns": 40,
  "distinct_fail_flops": 118,
  "lots_affected": 3,
  "fail_type_breakdown": { "SCAN_SHIFT": 812 },
  "example_chain_id": "core_inst/channel01",
  "rank": 1
}
```

`status` = `"satisfied"` if any failing chain, else `"no_failures_found"`.

---



## 12. Business Rules

- **BR-001:** A chain is "failing" iff it has ≥1 FAIL record in the loaded logs.
- **BR-002:** `fail_pct` = `fail_count / total_fail_records × 100`, rounded to 3 decimals.
- **BR-003:** Ranking is by `fail_count` descending; ties broken deterministically by chain name.
- **BR-004:** No magic numbers in code — all tunables live in `config.yaml`.

---



## 13. Key Engineering Rules

- Never hallucinate chains or counts — every number traces to a parsed record.
- Validate/normalize schema before aggregation (`normalize_failure_schema`).
- Preserve tester terminology (`chain`, `fail_flop_id`, `SCAN_SHIFT`).
- Deterministic output: identical logs ⇒ byte-identical aggregates.

---



## 14. Constraints

- Supported log formats: Tessent + compact inline multi-channel.
- Default chain-length fallback `234` when STIL/topology unavailable.
- Cache backend: Parquet (snappy) only.
- Result reflects loaded subset when `max_per_lot` is set.

---



## 15. API Specification


| Field        | Value                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------ |
| **Endpoint** | `GET /api/v1/kpi/failing_chains/workspace`                                                                   |
| **Method**   | GET                                                                                                          |
| **Query**    | `mode` (live/export), `min_observations` (default 2)                                                         |
| **Also**     | `GET /api/v1/diagnosis/dashboard` returns the `failing_chains` KPI tile                                      |
| **Response** | KPI workspace JSON (panels: ranking table + JSON data table)                                                 |
| **Errors**   | 200 with empty `failing_chains` when no FAILs; 500 on engine error (returns `_build_unavailable_dashboard`). |


---



## 16. Database Design

No relational DB. Persistence:

- **Parquet cache:** `data/cache/logs_<sha1>.parquet` (parsed failures keyed by path/mtime/size).
- **JSON artifact:** `output/SCD-FR-001_failing_scan_chains.json`.

---



## 17. Dashboard Integration

- **Screen:** Overview section, KPI tile `failing_chains`.
- **Action:** Click tile → drill-down modal (`KpiWorkspaceModal.tsx`).
- **Outputs shown:** `RankingBarChart.tsx` (chains by fail count) + `JsonDataTable.tsx` (full table).

---



## 18. AI Workflow (Step-by-Step)

1. Discover logs (`parser.discover_logs`) and load/parse to DataFrame (warm Parquet cache if available).
2. Normalize schema (`schema.normalize_failure_schema`).
3. Enrich with ML (`ml_pipeline.apply_failure_ml`) — shared pipeline.
4. `df.groupby("chain")`; compute `fail_count=len(sub)`, `fail_pct`, `distinct_patterns=nunique(pattern_id)`, `distinct_fail_flops=nunique(fail_flop_id)`, `lots_affected=nunique(lot_id)`, `fail_type_breakdown=value_counts(fail_type)`.
5. Sort by `fail_count` desc; assign `rank` 1..N.
6. Assemble summary + serialize to JSON with `status`.

---



## 19. Error Handling


| Error             | Cause                     | Action                                                     |
| ----------------- | ------------------------- | ---------------------------------------------------------- |
| Empty failure set | No FAIL records / no logs | Emit `status="no_failures_found"`, empty `failing_chains`. |
| Missing column    | Non-canonical log         | `normalize_failure_schema` alias-maps; fills defaults.     |
| Parse failure     | Corrupt log               | Skip file, log warning, continue with remaining logs.      |


---



## 20. Logging & Monitoring

- **Logs:** `output/run_logs/` rotating (INFO).
- **Metrics:** `logs_parsed`, `total_fail_records`, `distinct_failing_chains` in artifact `inputs`/`summary`.
- **Alerts:** N/A (batch/offline).

---



## 21. Security

- **Authentication/authorization:** None (internal engineering tool; localhost/containers).
- **Data handling:** Test data stays on local/volume-mounted storage; no external transmission.

---



## 22. Test Cases


| TC ID     | Requirement | Steps                                        | Expected Result                                | Status |
| --------- | ----------- | -------------------------------------------- | ---------------------------------------------- | ------ |
| TC-001-01 | FR-001      | Run `build_fr001` on a fixture with 2 chains | `distinct_failing_chains == 2`, ranks assigned | Pass   |
| TC-001-02 | FR-001      | Empty DataFrame                              | `status == "no_failures_found"`                | Pass   |
| TC-001-03 | FR-001      | `sum(fail_pct)` ≈ 100 for full set           | Percentages consistent                         | Pass   |


---



## 23. Acceptance Criteria

- Every chain with FAILs appears exactly once with correct `fail_count` and `rank`.
- `distinct_failing_chains` equals unique `chain` count among FAILs.
- JSON validates against the §11 schema; `status` reflects data presence.

---



## 24. Risks & Assumptions

- **Risk:** Parser mis-tags chain names for a new log dialect → mitigation: alias map + unit tests.
- **Assumption:** Loaded logs represent the population of interest (respect `max_per_lot`).

---



## 25. Dependencies

- Internal: `parser`, `schema`, `disk_cache`, `ml_pipeline`.
- External: pandas, numpy, pyarrow.
- Consumes the same parse pipeline as FR-002…FR-009.

---



## 26. Traceability Matrix


| FR         | Module/Function              | Artifact                              | TC            | AC  |
| ---------- | ---------------------------- | ------------------------------------- | ------------- | --- |
| SCD-FR-001 | `export_outputs.build_fr001` | `SCD-FR-001_failing_scan_chains.json` | TC-001-01..03 | §23 |


---



## 27. Reviewer Checklist

- [ ] Aggregation matches parsed record counts.
- [ ] Ranking deterministic and descending.
- [ ] Schema keys present and typed.
- [ ] Empty-data path returns correct status.

---



## 28. Approval


| Approver          | Date | Remarks |
| ----------------- | ---- | ------- |
| DFT Lead          |      |         |
| Yield Engineering |      |         |


