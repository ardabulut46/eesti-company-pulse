"""Freshness check: is each source still being checked, and is its content still moving?

Two different failures look the same in a dashboard ("old data"), so they are reported apart:
- check_age: days since our pipeline last contacted the publisher (our scheduler is broken).
- content_age: days since the publisher's newest Last-Modified we stored (the publisher stopped,
  or moved the file to a new URL that discovery does not find).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime

from pulse.config import Paths
from pulse.snapshots import read_manifest
from pulse.sources import family_of


@dataclass
class Freshness:
    source: str
    last_checked: datetime | None
    last_content: datetime | None
    check_age_days: float | None
    content_age_days: float | None
    warn_days: int
    error_days: int

    @property
    def status(self) -> str:
        ages = [a for a in (self.check_age_days, self.content_age_days) if a is not None]
        if len(ages) < 2:
            return "error"
        worst = max(ages)
        if worst > self.error_days:
            return "error"
        if worst > self.warn_days:
            return "warn"
        return "ok"


def _parse(ts: str) -> datetime | None:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if ts else None


def check(paths: Paths, now: datetime | None = None) -> list[Freshness]:
    now = now or datetime.now(UTC)
    last_checked: dict[str, datetime] = {}
    if paths.checks.exists():
        with paths.checks.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                t = _parse(row["checked_at_utc"])
                if t and (row["source"] not in last_checked or t > last_checked[row["source"]]):
                    last_checked[row["source"]] = t
    last_content: dict[str, datetime] = {}
    for s in read_manifest(paths):
        t = _parse(s.last_modified_utc) or _parse(s.retrieved_at_utc)
        # Snapshots taken before the downloader existed have no checks.csv row.
        r = _parse(s.retrieved_at_utc)
        if r and (s.source not in last_checked or r > last_checked[s.source]):
            last_checked[s.source] = r
        if t and (s.source not in last_content or t > last_content[s.source]):
            last_content[s.source] = t

    out = []
    for source in sorted(set(last_checked) | set(last_content)):
        spec = family_of(source)
        lc, lo = last_checked.get(source), last_content.get(source)
        out.append(
            Freshness(
                source,
                lc,
                lo,
                round((now - lc).total_seconds() / 86400, 1) if lc else None,
                round((now - lo).total_seconds() / 86400, 1) if lo else None,
                spec.freshness_warn_days,
                spec.freshness_error_days,
            )
        )
    return out
