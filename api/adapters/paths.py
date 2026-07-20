"""Resolve project paths and ensure ``src/`` is importable."""

from __future__ import annotations

import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = API_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"
CACHE_DIR = DATA_DIR / "cache"


def ensure_src_on_path() -> Path:
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)
    return SRC_DIR
