from datetime import UTC, datetime

from pulse import freshness
from pulse.snapshots import CHECK_FIELDS, MANIFEST_FIELDS, _append


def _snapshot(paths, source, retrieved, last_modified):
    _append(
        paths.manifest,
        MANIFEST_FIELDS,
        dict(
            source=source,
            url="u",
            retrieved_at_utc=retrieved,
            last_modified_utc=last_modified,
            cutoff_date="",
            size_bytes=1,
            content_length="1",
            sha256=source + retrieved,
            local_path=f"raw/{source}/x/f",
        ),
    )


def test_content_age_and_check_age_are_separate(paths):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    _snapshot(paths, "rik_basic", "2026-09-20T12:00:00Z", "2026-09-20T08:00:00Z")
    _append(
        paths.checks,
        CHECK_FIELDS,
        dict(
            checked_at_utc="2026-09-24T11:00:00Z",
            source="rik_basic",
            url="u",
            result="unchanged",
            sha256="s",
            size_bytes=1,
            local_path="p",
        ),
    )
    _snapshot(paths, "emta_current", "2026-07-11T12:00:00Z", "2026-07-10T06:00:00Z")

    result = {f.source: f for f in freshness.check(paths, now=now)}
    basic = result["rik_basic"]
    assert basic.check_age_days < 1  # we checked this morning ...
    assert basic.content_age_days > 4  # ... but the publisher has not changed the file
    assert basic.status == "error"
    assert result["emta_current"].status == "ok"  # 76 days is normal for a quarterly source
