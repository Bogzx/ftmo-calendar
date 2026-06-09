"""Simple, self-hosted, anonymous usage statistics.

Counts page views, unique visitors (random first-party cookie id), feed pulls,
and unique feed clients (hash of address + user agent). No third parties, no
personal data: visitor ids are random tokens, client hashes are one-way.
Persisted to stats.json next to the state file; daily history kept 30 days.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_HISTORY_DAYS = 30
_MAX_TRACKED_IDS = 10_000  # per day; cap memory on pathological traffic


class StatsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._days: dict[str, dict[str, int]] = {}
        self._today = ""
        self._seen_visitors: set[str] = set()
        self._seen_clients: set[str] = set()
        self._load()

    def record_page_view(self, visitor_id: str, now: datetime | None = None) -> None:
        with self._lock:
            day = self._roll(now)
            day["views"] += 1
            if (
                visitor_id not in self._seen_visitors
                and len(self._seen_visitors) < _MAX_TRACKED_IDS
            ):
                self._seen_visitors.add(visitor_id)
                day["visitors"] += 1
            self._save()

    def record_feed_hit(self, client_hash: str, now: datetime | None = None) -> None:
        with self._lock:
            day = self._roll(now)
            day["feed_hits"] += 1
            if client_hash not in self._seen_clients and len(self._seen_clients) < _MAX_TRACKED_IDS:
                self._seen_clients.add(client_hash)
                day["feed_clients"] += 1
            self._save()

    def snapshot(self, now: datetime | None = None) -> dict:
        with self._lock:
            self._roll(now)
            history = {key: dict(value) for key, value in self._days.items() if key != self._today}
            return {
                "today": dict(self._days[self._today]),
                "days": history,
                "totals": {
                    "views": sum(d["views"] for d in self._days.values()),
                    "feed_hits": sum(d["feed_hits"] for d in self._days.values()),
                },
            }

    def _roll(self, now: datetime | None) -> dict[str, int]:
        """Ensure today's bucket exists; archive and trim on day change."""
        today = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
        if today != self._today:
            self._today = today
            self._seen_visitors = set()
            self._seen_clients = set()
            self._days.setdefault(
                today, {"views": 0, "visitors": 0, "feed_hits": 0, "feed_clients": 0}
            )
            for stale in sorted(self._days)[:-_HISTORY_DAYS]:
                del self._days[stale]
        return self._days[self._today]

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
            self._days = {
                key: {
                    "views": int(value.get("views", 0)),
                    "visitors": int(value.get("visitors", 0)),
                    "feed_hits": int(value.get("feed_hits", 0)),
                    "feed_clients": int(value.get("feed_clients", 0)),
                }
                for key, value in data.get("days", {}).items()
            }
            self._today = data.get("today", "")
            self._seen_visitors = set(data.get("seen_visitors", []))
            self._seen_clients = set(data.get("seen_clients", []))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as e:
            logger.warning("Stats file %s is corrupt (%s); starting fresh", self._path, e)
            self._days = {}

    def _save(self) -> None:
        payload = {
            "today": self._today,
            "days": self._days,
            "seen_visitors": sorted(self._seen_visitors),
            "seen_clients": sorted(self._seen_clients),
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self._path)
