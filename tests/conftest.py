"""Shared test setup.

The point of this file is one guarantee: **no test reads a real feed cache.**

``live.feeds`` caches the Wikipedia-sourced calendar and draw sheets under ``data/``. Those
files are gitignored build artifacts, so they exist on a developer's machine and not in CI —
which means a test that quietly falls back to reading them passes locally and fails on the
runner. That is exactly what happened: ``test_parse_carries_the_venue_city`` called
``espn.parse`` without supplying a calendar, picked up the local one, and only failed once CI
ran it with no cache present.

Patching call sites one at a time invites the same bug again, so instead the cache paths are
redirected into a per-test temp directory for the whole suite. A test that wants feed data
now has to pass it in explicitly, and one that doesn't gets a consistent empty cache
everywhere.
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
