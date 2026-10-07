"""Filesystem layout. Every path can be redirected with PULSE_DATA_DIR (tests and CI use this)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    data: Path

    @property
    def raw(self) -> Path:
        """Immutable downloaded files: raw/<source>/<snapshot_id>/<filename>."""
        return self.data / "raw"

    @property
    def manifest(self) -> Path:
        """One row per stored snapshot (new content only)."""
        return self.raw / "manifest.csv"

    @property
    def checks(self) -> Path:
        """One row per download attempt, including 'unchanged' results."""
        return self.raw / "checks.csv"

    @property
    def lake(self) -> Path:
        """Parquet copies of raw snapshots: lake/<source>/<snapshot_id>/data.parquet."""
        return self.data / "lake"

    @property
    def conversions(self) -> Path:
        return self.lake / "conversions.csv"

    @property
    def warehouse(self) -> Path:
        return self.data / "warehouse" / "pulse.duckdb"

    @property
    def tmp(self) -> Path:
        return self.data / "tmp"


def get_paths() -> Paths:
    return Paths(Path(os.environ.get("PULSE_DATA_DIR", REPO_ROOT / "data")).resolve())
