from datetime import UTC, datetime
from pathlib import Path

from ftmo_calendar.stats import StatsStore

DAY1 = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
DAY1_LATER = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
DAY2 = datetime(2026, 6, 11, 9, 0, tzinfo=UTC)


def test_counts_views_and_unique_visitors(tmp_path: Path) -> None:
    stats = StatsStore(tmp_path / "stats.json")
    stats.record_page_view("alice", now=DAY1)
    stats.record_page_view("alice", now=DAY1_LATER)
    stats.record_page_view("bob", now=DAY1_LATER)
    today = stats.snapshot(now=DAY1_LATER)["today"]
    assert today["views"] == 3
    assert today["visitors"] == 2


def test_counts_feed_hits_and_clients(tmp_path: Path) -> None:
    stats = StatsStore(tmp_path / "stats.json")
    stats.record_feed_hit("client-a", now=DAY1)
    stats.record_feed_hit("client-a", now=DAY1)
    stats.record_feed_hit("client-b", now=DAY1)
    today = stats.snapshot(now=DAY1)["today"]
    assert today["feed_hits"] == 3
    assert today["feed_clients"] == 2


def test_day_rollover_archives_and_resets(tmp_path: Path) -> None:
    stats = StatsStore(tmp_path / "stats.json")
    stats.record_page_view("alice", now=DAY1)
    stats.record_page_view("alice", now=DAY2)  # new day
    snapshot = stats.snapshot(now=DAY2)
    assert snapshot["today"]["views"] == 1
    assert snapshot["days"]["2026-06-10"]["views"] == 1
    assert snapshot["days"]["2026-06-10"]["visitors"] == 1


def test_persistence_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    stats = StatsStore(path)
    stats.record_page_view("alice", now=DAY1)
    stats.record_feed_hit("client-a", now=DAY1)
    reloaded = StatsStore(path)
    today = reloaded.snapshot(now=DAY1)["today"]
    assert today["views"] == 1 and today["visitors"] == 1
    assert today["feed_hits"] == 1
    # uniqueness survives the restart
    reloaded.record_page_view("alice", now=DAY1_LATER)
    assert reloaded.snapshot(now=DAY1_LATER)["today"]["visitors"] == 1


def test_corrupt_file_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "stats.json"
    path.write_text("{nope", encoding="utf-8")
    stats = StatsStore(path)
    stats.record_page_view("alice", now=DAY1)
    assert stats.snapshot(now=DAY1)["today"]["views"] == 1


def test_history_kept_to_30_days(tmp_path: Path) -> None:
    from datetime import timedelta

    stats = StatsStore(tmp_path / "stats.json")
    base = datetime(2026, 4, 1, tzinfo=UTC)
    for day in range(35):
        stats.record_page_view("v", now=base + timedelta(days=day))
    snapshot = stats.snapshot(now=base + timedelta(days=34))
    assert len(snapshot["days"]) <= 30
