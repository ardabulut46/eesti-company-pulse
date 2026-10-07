"""Immutable snapshot store.

Rules:
- A file is stored once per (source, SHA-256). Downloading unchanged content adds nothing to the
  manifest; it only appends an 'unchanged' row to checks.csv.
- A stored file is never modified or overwritten. Its directory is the snapshot_id:
  the UTC retrieval date, or date + time if the same source changed twice in one day.
- A download whose size differs from Content-Length is rejected before anything is stored.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from pulse.config import Paths
from pulse.sources import USER_AGENT, Resolved

MANIFEST_FIELDS = [
    "source",
    "url",
    "retrieved_at_utc",
    "last_modified_utc",
    "cutoff_date",
    "size_bytes",
    "content_length",
    "sha256",
    "local_path",
]
CHECK_FIELDS = ["checked_at_utc", "source", "url", "result", "sha256", "size_bytes", "local_path"]


class IncompleteDownload(RuntimeError):
    """Received byte count differs from Content-Length. Safe to retry."""


@dataclass
class Snapshot:
    source: str
    url: str
    retrieved_at_utc: str
    last_modified_utc: str
    cutoff_date: str
    size_bytes: int
    content_length: str
    sha256: str
    local_path: str  # relative to the data directory

    @property
    def snapshot_id(self) -> str:
        return Path(self.local_path).parent.name


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_manifest(paths: Paths) -> list[Snapshot]:
    if not paths.manifest.exists():
        return []
    with paths.manifest.open(newline="", encoding="utf-8") as fh:
        return [
            Snapshot(**{**row, "size_bytes": int(row["size_bytes"])}) for row in csv.DictReader(fh)
        ]


def _append(path: Path, fields: list[str], row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)


def _filename(url: str, response: requests.Response) -> str:
    cd = response.headers.get("content-disposition", "")
    if "filename=" in cd:
        return cd.split("filename=")[-1].strip().strip('"')
    return unquote(Path(urlparse(url).path).name)


def _stream_to_tmp(response: requests.Response, tmp: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with tmp.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def fetch(
    resolved: Resolved,
    paths: Paths,
    session: requests.Session | None = None,
    now: datetime | None = None,
    retries: int = 3,
    backoff_seconds: float = 5.0,
) -> tuple[str, Snapshot | None]:
    """Download one source. Returns ('new', snapshot) or ('unchanged', None)."""
    session = session or requests.Session()
    for attempt in range(1, retries + 1):
        try:
            return _fetch_once(resolved, paths, session, now or datetime.now(UTC))
        except (IncompleteDownload, requests.ConnectionError, requests.Timeout):
            if attempt == retries:
                raise
            time.sleep(backoff_seconds * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def _fetch_once(
    resolved: Resolved, paths: Paths, session: requests.Session, now: datetime
) -> tuple[str, Snapshot | None]:
    paths.tmp.mkdir(parents=True, exist_ok=True)
    tmp = paths.tmp / f"{resolved.source}.part"
    try:
        with session.get(
            resolved.url, stream=True, timeout=120, headers={"User-Agent": USER_AGENT}
        ) as r:
            r.raise_for_status()
            sha, size = _stream_to_tmp(r, tmp)
            content_length = r.headers.get("content-length", "")
            last_modified = r.headers.get("last-modified")
            headers_text = "\n".join(f"{k}: {v}" for k, v in r.headers.items())
            filename = _filename(resolved.url, r)
    except requests.exceptions.ChunkedEncodingError as exc:
        # urllib3 notices the connection closed before Content-Length bytes arrived.
        tmp.unlink(missing_ok=True)
        raise IncompleteDownload(f"{resolved.source}: connection closed early ({exc})") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    if content_length and int(content_length) != size:
        tmp.unlink(missing_ok=True)
        raise IncompleteDownload(f"{resolved.source}: got {size} bytes, expected {content_length}")

    checked = _iso(now)
    known = {s.sha256: s for s in read_manifest(paths) if s.source == resolved.source}
    if sha in known:
        tmp.unlink()
        _append(
            paths.checks,
            CHECK_FIELDS,
            dict(
                checked_at_utc=checked,
                source=resolved.source,
                url=resolved.url,
                result="unchanged",
                sha256=sha,
                size_bytes=size,
                local_path=known[sha].local_path,
            ),
        )
        return "unchanged", None

    snapshot_id = now.strftime("%Y-%m-%d")
    target_dir = paths.raw / resolved.source / snapshot_id
    if target_dir.exists():  # same source changed twice in one UTC day
        snapshot_id = now.strftime("%Y-%m-%dT%H%M%SZ")
        target_dir = paths.raw / resolved.source / snapshot_id
    target_dir.mkdir(parents=True)
    target = target_dir / filename
    shutil.move(tmp, target)
    target.chmod(0o444)  # immutable by convention and by permission
    (target_dir / "headers.txt").write_text(headers_text + "\n", encoding="utf-8")

    snap = Snapshot(
        source=resolved.source,
        url=resolved.url,
        retrieved_at_utc=checked,
        last_modified_utc=_iso(parsedate_to_datetime(last_modified)) if last_modified else "",
        cutoff_date=resolved.cutoff_date.isoformat() if resolved.cutoff_date else "",
        size_bytes=size,
        content_length=content_length,
        sha256=sha,
        local_path=str(target.relative_to(paths.data)),
    )
    (target_dir / f"{filename}.meta.json").write_text(
        json.dumps(asdict(snap), indent=2) + "\n", encoding="utf-8"
    )
    _append(paths.manifest, MANIFEST_FIELDS, asdict(snap))
    _append(
        paths.checks,
        CHECK_FIELDS,
        dict(
            checked_at_utc=checked,
            source=resolved.source,
            url=resolved.url,
            result="new",
            sha256=sha,
            size_bytes=size,
            local_path=snap.local_path,
        ),
    )
    return "new", snap


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(paths: Paths) -> list[str]:
    """Re-hash every stored snapshot. Returns a list of problems (empty = all good).

    Also writes a missing .meta.json sidecar for snapshots that predate the downloader.
    """
    problems = []
    seen: set[tuple[str, str]] = set()
    for s in read_manifest(paths):
        f = paths.data / s.local_path
        if (s.source, s.sha256) in seen:
            problems.append(f"{s.local_path}: duplicate manifest entry for the same content")
        seen.add((s.source, s.sha256))
        if not f.exists():
            problems.append(f"{s.local_path}: missing")
            continue
        if f.stat().st_size != s.size_bytes:
            problems.append(f"{s.local_path}: size {f.stat().st_size} != manifest {s.size_bytes}")
            continue
        if sha256_file(f) != s.sha256:
            problems.append(f"{s.local_path}: sha256 mismatch")
            continue
        sidecar = f.with_name(f.name + ".meta.json")
        if not sidecar.exists():
            sidecar.write_text(json.dumps(asdict(s), indent=2) + "\n", encoding="utf-8")
    return problems
