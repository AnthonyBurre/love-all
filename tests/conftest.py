"""Shared test setup: no test reads a real feed cache.

``live.feeds`` caches the Wikipedia calendar and draw sheets under gitignored ``data/``, so
they exist locally but not in CI, and a test that reads them passes locally and fails there.
The cache paths are redirected into a per-test temp directory for the whole suite, so a test
that wants feed data has to pass it in.
"""

import pytest

from match_charting_project.live import espn, feeds


@pytest.fixture(autouse=True)
def _isolate_feed_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "CALENDAR", tmp_path / "calendar.json")
    monkeypatch.setattr(feeds, "DRAWS", tmp_path / "draws.json")
    # Same guarantee for the scoreboard cache: it decides whether ``espn._fetch`` skips the
    # network at all, so a test reading the developer's real copy would be gated on whatever
    # tournament happened to be running that week.
    monkeypatch.setattr(espn, "_CACHE", tmp_path / "live")
