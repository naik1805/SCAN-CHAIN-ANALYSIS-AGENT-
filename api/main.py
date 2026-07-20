"""
Scan Diagnosis FastAPI shell.

Run from project root:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.routers.diagnosis import router as diagnosis_router  # noqa: E402

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify live diagnosis path on startup — fail loud in logs, not silent 960 fallback."""
    from api.adapters.diagnosis_service import validate_live_path

    result = validate_live_path()
    app.state.live_validation = result
    if result.get("ok"):
        log.info(
            "Live path OK: %s failures from %s logs (loader=%s)",
            result.get("failure_records"),
            result.get("log_file_count"),
            result.get("load_source"),
        )
    else:
        log.error("LIVE PATH VALIDATION FAILED: %s", result.get("errors"))
    yield


app = FastAPI(
    title="Scan Chain Diagnosis API",
    description="Thin FastAPI adapters over the existing Python diagnosis engine (algorithms unchanged).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(diagnosis_router)


@app.get("/")
def root():
    return {
        "service": "scan-chain-diagnosis-api",
        "docs": "/docs",
        "health": "/api/v1/health",
        "dashboard": "/api/v1/diagnosis/dashboard",
    }
