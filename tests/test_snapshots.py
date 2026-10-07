import os
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pulse import snapshots
from pulse.sources import Resolved

from synthetic_sources import Server

DAY1 = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
DAY2 = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)


@pytest.fixture
def served(tmp_path):
    d = tmp_path / "served"
    d.mkdir()
    with Server(d) as srv:
        yield d, srv


def test_new_then_unchanged_then_changed(paths, served):
    served_dir, srv = served
    (served_dir / "f.csv").write_bytes(b"a;b\n1;2\n")
    src = Resolved("rik_basic", f"{srv.base_url}/f.csv")

    result, snap = snapshots.fetch(src, paths, now=DAY1)
    assert result == "new"
    assert snap.local_path == "raw/rik_basic/2026-09-24/f.csv"
    assert snap.size_bytes == 8
    stored = paths.data / snap.local_path
    assert stored.read_bytes() == b"a;b\n1;2\n"
    assert not os.access(stored, os.W_OK), "stored snapshots are read-only"
    assert (stored.parent / "f.csv.meta.json").exists()

    # Same content again: nothing new stored, but the check is logged.
    result, snap2 = snapshots.fetch(src, paths, now=DAY2)
    assert (result, snap2) == ("unchanged", None)
    assert len(snapshots.read_manifest(paths)) == 1
    assert paths.checks.read_text().count("unchanged") == 1

    # Changed content on the same day as an existing snapshot gets a time-suffixed directory.
    (served_dir / "f.csv").write_bytes(b"a;b\n1;3\n")
    result, snap3 = snapshots.fetch(src, paths, now=DAY1.replace(hour=15))
    assert result == "new"
    assert snap3.snapshot_id == "2026-09-24T150000Z"
    assert len(snapshots.read_manifest(paths)) == 2
    assert snapshots.verify(paths) == []


def test_incomplete_download_is_rejected_and_nothing_stored(paths):
    class Liar(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"only a few bytes")

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Liar)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        src = Resolved("rik_basic", f"http://127.0.0.1:{httpd.server_address[1]}/x.csv")
        with pytest.raises(snapshots.IncompleteDownload):
            snapshots.fetch(src, paths, now=DAY1, retries=2, backoff_seconds=0)
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert snapshots.read_manifest(paths) == []
    assert not (paths.raw / "rik_basic").exists()
    assert not list(paths.tmp.glob("*.part")), "partial download must be cleaned up"


def test_verify_detects_a_modified_snapshot(paths, served):
    served_dir, srv = served
    (served_dir / "f.csv").write_bytes(b"a;b\n1;2\n")
    _, snap = snapshots.fetch(Resolved("rik_basic", f"{srv.base_url}/f.csv"), paths, now=DAY1)
    stored = paths.data / snap.local_path
    stored.chmod(0o644)
    stored.write_bytes(b"a;b\n9;9\n")
    problems = snapshots.verify(paths)
    assert problems == [f"{snap.local_path}: sha256 mismatch"]
