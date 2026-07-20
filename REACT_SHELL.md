# Scan Diagnosis React Shell

Enterprise **Next.js** UI + **FastAPI** adapters over the existing Python diagnosis engine.  
Streamlit has been removed — this stack is the only UI.

## Folder structure

```text
api/
  main.py                 # FastAPI app (CORS, routers)
  requirements.txt
  adapters/
    data_loader.py        # parse/cache/STIL via existing src modules
    diagnosis_service.py  # KPI/dashboard/workspace aggregation (no algo changes)
    paths.py
  models/schemas.py
  routers/diagnosis.py    # /api/v1/...

frontend/
  package.json
  src/
    app/                  # Next.js App Router
    components/scan-diagnosis/
    lib/kpiDrillDown/     # types, mock, api client, workspace builder, profiles
```

## Run (two terminals)

### 1) FastAPI (port 8000)

```bash
cd "D:\scan chain dianosis agent"
pip install -r api/requirements.txt
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

Health: http://127.0.0.1:8000/api/v1/health  
Docs: http://127.0.0.1:8000/docs

### 2) Next.js (port 3000)

```bash
cd "D:\scan chain dianosis agent\frontend"
copy .env.local.example .env.local
npm install
npm run dev
```

UI: http://localhost:3000

### Modes

| Variable | Values | Behavior |
|----------|--------|----------|
| `NEXT_PUBLIC_API_MODE` | `live` (default) | Call FastAPI; fall back to mock if unreachable |
| `NEXT_PUBLIC_API_MODE` | `mock` | Use `diagnosisMock.ts` only |
| `API_MODE` (backend) | `live` / `mock` | Same for server-side responses |

Footer shows: **Data source: FastAPI** (live/exports) or **Mock JSON**.

## Live vs mock

**Live** (`diagnosis_service`):
- Calls existing helpers: `rank_chains_by_frequency`, `detect_chain_breaks`, `locate_failing_cells`, `build_topology_analysis`
- Loads failures via existing parser + disk cache; **`ml_pipeline.apply_failure_ml`** (RandomForest + IsolationForest) runs on every load before localization
- If live compute fails → aggregates real `output/SCD-FR-*.json` exports
- Pending Reviews = honest **N/A** (no review-queue entity; tied to report export status)

**Mock**: decorative numbers matching the COMPTY mockup (not used as business truth).

## Algorithms

Diagnosis algorithms under `src/chain_breaks.py`, `chain_ranking.py`, parsers, topology, ML, and report generators’ core math are **not modified**. API only imports and calls them.
