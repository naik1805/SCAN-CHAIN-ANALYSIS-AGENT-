# Technical AI Agent Specification — SCD-FR-003

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-003) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Scan Topology Analysis Agent |
| **Requirement ID** | SCD-FR-003 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Scan Topology Agent v1.0 |

---

## 2. Project Overview

**Objective:** Reconstruct the DFT scan topology (chains, cell order, connectivity, clock domains, scan-enable, EDT compression association, physical placement, chain balance, shared resources) from STIL ScanStructures or `hardware_topology.md`.

**Scope of this FR:** Full topology model that other FRs (cell localization, correlation, breaks) enrich against.

**Stakeholders:** DFT engineers, layout/PD engineers.

---

## 3. Business Objective

**Problem:** Diagnosis needs to know how cells connect (SI→cells→SO), which clock/decompressor drives each chain, and where cells sit physically.

**Expected outcome:** A machine-readable topology graph + per-chain detail powering visualizers and downstream analysis.

**KPI:** `topology_chains` (engineering section).

---

## 4. Technical Overview

**Workflow:** `stil_parser.parse_stil_scan_structures` / `parse_hardware_topology_md` → `topology_analysis.build_topology_analysis` → `export_outputs.build_fr003` → JSON + connectivity graph.

**Technologies:** STIL/Markdown parsing, deterministic serpentine placement model, hashlib micro-offsets, numpy/pandas.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, TailwindCSS, Recharts, framer-motion |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | None (deterministic structural analysis) |
| **Framework** | pandas, numpy, hashlib |
| **Database** | STIL/MD inputs; JSON artifacts |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Parse chain identity, `ScanLength`, `ScanIn/Out`, `ScanMasterClock`, `ScanInversion`.
- Build cell order + per-cell connectivity (SI→first cell→shift links→SO).
- Derive decompressor/compactor pin association and compression ratio.
- Compute chain balance and shared resources; place cells physically (serpentine).
- Emit connectivity graph (JTAG→TAP→EDT→chains).

**Exclusions:** Failure aggregation and localization (FR-001/002).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-003 |
| **Description** | Analyze and export full scan topology incl. connectivity graph, clock domains, compression association, chain balance, physical placement. |
| **Priority** | High (topology feeds FR-002/005/006). |
| **Inputs** | chain_map (STIL `ScanStructures` or `hardware_topology.md`), optional failures DataFrame, `log_dir` (header metadata). |
| **Outputs** | `SCD-FR-003_scan_topology.json` (see §11). |
| **Processing Logic** | Per-chain detail + graph + balance + placement (see §18). |
| **Dependencies** | `stil_parser`, `parser` (log metadata), `locate_cells`; numpy, pandas, hashlib. |

---

## 8. Non-Functional Requirements

- **Response time:** Sub-second for typical chain counts.
- **Scalability:** Handles many chains × hundreds of cells; graph built with counts.
- **Logging:** INFO; STIL source and chain count logged.
- **Availability:** Falls back to `hardware_topology.md`, then synthesized defaults (chain length `234`).

---

## 9. AI Behavior Specification

- **Role:** Deterministic structural reconstructor.
- **Workflow:** parse → per-chain detail → aggregate summary → graph.
- **Decision logic:** pin association `edt_channels_in[idx % num_channels]`; `instance_type` from `core_inst`/`phy_inst`; `scan_enable=SCAN_ENABLE_{clock}_{SLOW|FAST|STANDARD}`.
- **Limitations:** Physical placement is a modeled serpentine (not GDS-exact) — clearly a layout estimate.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `chain_map` | dict | Yes | From STIL/MD; fields `ScanLength`, `ScanIn`, `ScanOut`, `ScanMasterClock`, `ScanInversion`. |
| `failures_df` | DataFrame | No | Adds `log_failure_summary` per chain. |
| `log_dir` | path | No | Reads log header die/context metadata. |

---

## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-003_scan_topology.json`.

**Top keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `inputs{stil_file, logs_analyzed, failure_records_analyzed}`, `number_of_scan_chains`, `summary`, `chain_balance`, `shared_resources`, `compression_association`, `connectivity_graph{node_count, edge_count, nodes[], edges[]}`, `chains[]`.

**`summary`:** `total_scan_chains`, `total_flip_flops`, `max/min/mean_chain_length`, `chain_balance`, `compression`, `active_clocks`, `scan_enable_signals`, `logs_analyzed`, `failure_records_analyzed`, `die_context_from_logs`.

**Per-chain (`build_chain_detail`):** `scan_chain_id`, `chain_short_name`, `chain_name`, `instance_type`, `chain_length`, `scan_cell_order`, `scan_cell_names`, `scan_input_si`, `scan_output_so`, `scan_cell_connectivity`, `clock_domain`, `scan_enable_se`, `scan_master_clock`, `scan_inversion`, `compression_association{decompressor_pin, compactor_pin, hierarchical_path}`, `physical_locations[]`, `cells[]`, `log_failure_summary`.

---

## 12. Business Rules

- **BR-001:** `compression_ratio = round(total_chains / unique_decompressor_pins, 2)`.
- **BR-002:** Chain balance `imbalance_pct = (max-min)/mean × 100`; `is_balanced = (max==min)`.
- **BR-003:** Physical model: `DIE_W_UM=DIE_H_UM=4000`, `rows_per_chain=5`, serpentine + md5 micro-offset.
- **BR-004:** `hierarchical_path = U_core/reg_c{idx}_ff`.

---

## 13. Key Engineering Rules

- Never fabricate connectivity — derive from parsed STIL/MD only.
- Preserve DFT terminology (decompressor, compactor, EDT, ScanMasterClock).
- Deterministic placement (md5-seeded offsets, fixed die dims).
- All model constants documented (no magic numbers in logic paths).

---

## 14. Constraints

- Compression logic label fixed: `"Tessent EDT Decompressor & Compactor"`.
- Placement is a modeled estimate, band per chain = `die_h / num_chains`.
- Chain-length fallback `234`.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/topology_chains/workspace` |
| **Method** | GET |
| **Response** | Panels: `topology_overview`, `topology_chain_balance`, `topology_shared_resources`, `topology_compression`, `topology_registry`, `topology_connectivity`, `topology_schematic` |
| **Errors** | Empty topology → overview with 0 chains. |

---

## 16. Database Design

- Inputs: STIL file (`resolve_active_stil_file`) or `hardware_topology.md` (`find_topology_md_file`).
- Artifact: `output/SCD-FR-003_scan_topology.json`.

---

## 17. Dashboard Integration

- **Screen:** Engineering section, KPI `topology_chains`.
- **Action:** Drill-down → `TopologyGraph.tsx`, `topology/ScanTopologyPanels.tsx`, `topology/TopologyConnectivityGraph.tsx`.
- **Outputs:** Overview, chain balance, shared resources, compression, connectivity graph, schematic.

---

## 18. AI Workflow (Step-by-Step)

1. Resolve STIL (`parse_stil_scan_structures`) or MD (`parse_hardware_topology_md`); enrich (`enrich_chain_topology`).
2. Per chain: `build_chain_detail` → cell order, connectivity (`si_to_first_cell`, `shift_link`, `last_cell_to_so`), clock/scan-enable, compression pins.
3. Physical placement via serpentine model + hash micro-offset (`cell_physical_location`).
4. `compute_chain_balance`, `compute_shared_resources`, `build_compression_association`.
5. `build_connectivity_graph` (JTAG→TAP→EDT engine→decompressor pins→chains→compactor pins).
6. Assemble summary + serialize.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| No STIL & no MD | Missing topology inputs | Synthesize defaults (length 234), mark source. |
| Malformed STIL | Parser error | Log warning, fall back to MD. |
| No failures | Optional input absent | Omit `log_failure_summary`. |

---

## 20. Logging & Monitoring

- **Logs:** STIL/MD source, chain count.
- **Metrics:** `total_scan_chains`, `total_flip_flops`, `compression`.
- **Alerts:** N/A.

---

## 21. Security

- No auth. STIL/topology files kept locally; no external calls.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-003-01 | FR-003 | Parse STIL fixture | Chains + cell order populated | Pass |
| TC-003-02 | FR-003 | Chain balance | `imbalance_pct` correct | Pass |
| TC-003-03 | FR-003 | Connectivity graph | `node_count`/`edge_count` consistent | Pass |

---

## 23. Acceptance Criteria

- Every parsed chain appears with cell order, clock, compression pins.
- Connectivity graph nodes/edges internally consistent.
- Summary matches per-chain aggregates.

---

## 24. Risks & Assumptions

- **Risk:** Placement mistaken for GDS-accurate; mitigation: labeled as modeled estimate.
- **Assumption:** STIL/MD is the authoritative topology source.

---

## 25. Dependencies

- Internal: `stil_parser`, `topology_analysis`, `parser`, `locate_cells`.
- External: numpy, pandas, hashlib.
- Consumed by: FR-002, FR-005, FR-006, FR-008.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-003 | `topology_analysis.build_topology_analysis`, `export_outputs.build_fr003` | `SCD-FR-003_scan_topology.json` | TC-003-01..03 | §23 |

---

## 27. Reviewer Checklist

- [ ] Cell order matches STIL.
- [ ] Compression pins/ratio correct.
- [ ] Graph consistent.
- [ ] Placement labeled as modeled.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| PD/Layout | | |
