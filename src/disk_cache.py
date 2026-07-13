"""
disk_cache.py — Persistent Parquet cache for parsed ATPG log data.

On the first call with a given set of log files, the full parse takes place and
the result is written to a `.parquet` file in the project `data/cache/` folder.
On every subsequent call with the *same* set of files (matched by path + mtime +
size), the parquet is read directly — no text parsing at all.

This cuts the cold-start from ~60-120 s down to ~2-3 s on warm runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Where the cache files land (relative to the caller's project root)
_CACHE_SUBDIR = "data/cache"


def _cache_key(paths_info: list[tuple[str, float, int]]) -> str:
    """Stable SHA-1 of the sorted (path, mtime, size) list."""
    canonical = sorted(paths_info)           # deterministic regardless of discovery order
    blob = json.dumps(canonical, separators=(",", ":"))
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _cache_dir(project_root: Path) -> Path:
    d = project_root / _CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_from_cache(
    paths_info: list[tuple[str, float, int]],
    project_root: Path,
) -> pd.DataFrame | None:
    """Return cached DataFrame if it exists, else None."""
    if not paths_info:
        return None
    key = _cache_key(paths_info)
    parquet_path = _cache_dir(project_root) / f"logs_{key}.parquet"
    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
            log.info("Cache HIT  -> %s (%d rows)", parquet_path.name, len(df))
            return df
        except Exception as exc:
            log.warning("Cache file corrupt, will re-parse: %s", exc)
            parquet_path.unlink(missing_ok=True)
    return None


def save_to_cache(
    df: pd.DataFrame,
    paths_info: list[tuple[str, float, int]],
    project_root: Path,
) -> None:
    """Persist *df* to disk so the next run can skip parsing."""
    if df.empty or not paths_info:
        return
    key = _cache_key(paths_info)
    parquet_path = _cache_dir(project_root) / f"logs_{key}.parquet"
    try:
        # Convert object columns that can be downcast to category for ~50% size saving
        df_out = df.copy()
        for col in ["chain", "fail_type", "failure_region", "root_cause_hint",
                    "predicted_root_cause", "lot_id", "source_file"]:
            if col in df_out.columns:
                df_out[col] = df_out[col].astype("category")
        df_out.to_parquet(parquet_path, index=False, compression="snappy")
        log.info("Cache WRITE -> %s (%d rows, %.1f MB)",
                 parquet_path.name, len(df),
                 parquet_path.stat().st_size / 1_048_576)
    except Exception as exc:
        log.warning("Could not write cache: %s", exc)


def invalidate_cache(project_root: Path) -> int:
    """Delete all cached parquet files.  Returns the number removed."""
    removed = 0
    for f in _cache_dir(project_root).glob("logs_*.parquet"):
        f.unlink()
        removed += 1
    return removed
