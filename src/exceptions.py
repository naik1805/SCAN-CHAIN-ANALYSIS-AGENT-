"""
exceptions.py — Custom exception hierarchy for the Scan Chain Diagnosis Agent.

All public-facing errors raised by the application derive from
``SCAError`` so callers can catch the entire family with one clause.

Hierarchy::

    SCAError
    ├── ParseError          Log or STIL file could not be parsed
    ├── ValidationError     Input DataFrame or config failed schema check
    ├── ModelError          ML model training or prediction failed
    └── CacheError          Disk cache read / write failed
"""

from __future__ import annotations


class SCAError(Exception):
    """Base exception for all Scan Chain Diagnosis Agent errors."""


class ParseError(SCAError):
    """Raised when a log file or STIL file cannot be parsed correctly.

    Args:
        message: Human-readable description of the failure.
        path: Optional path to the file that caused the error.
    """

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        suffix = f" [file: {path}]" if path else ""
        super().__init__(f"{message}{suffix}")


class ValidationError(SCAError):
    """Raised when input data fails schema or quality validation.

    Args:
        message: Human-readable description of the validation failure.
        missing_columns: Columns that were expected but not found.
    """

    def __init__(
        self,
        message: str,
        missing_columns: list[str] | None = None,
    ) -> None:
        self.missing_columns = missing_columns or []
        suffix = f" (missing: {self.missing_columns})" if self.missing_columns else ""
        super().__init__(f"{message}{suffix}")


class ModelError(SCAError):
    """Raised when ML model training or inference fails.

    Args:
        message: Human-readable description of the model error.
        model_name: Name of the model that failed (e.g. 'RandomForest').
    """

    def __init__(self, message: str, model_name: str | None = None) -> None:
        self.model_name = model_name
        suffix = f" [model: {model_name}]" if model_name else ""
        super().__init__(f"{message}{suffix}")


class CacheError(SCAError):
    """Raised when the Parquet disk cache cannot be read or written.

    Args:
        message: Human-readable description of the cache error.
        cache_path: Optional path to the cache file involved.
    """

    def __init__(self, message: str, cache_path: str | None = None) -> None:
        self.cache_path = cache_path
        suffix = f" [cache: {cache_path}]" if cache_path else ""
        super().__init__(f"{message}{suffix}")


__all__ = [
    "SCAError",
    "ParseError",
    "ValidationError",
    "ModelError",
    "CacheError",
]
