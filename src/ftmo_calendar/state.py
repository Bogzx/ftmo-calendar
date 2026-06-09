"""Persistent run state: which posts were seen and which events were created."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_VERSION = 2
_PRUNE_AFTER_DAYS = 45


@dataclass
class TrackedEvent:
    event_key: str
    google_event_id: str
    end: str  # ISO 8601, timezone-aware
    summary: str = ""  # display data for ICS export (v2)
    start: str = ""  # ISO 8601, timezone-aware (v2)


@dataclass
class PostState:
    content_hash: str
    last_seen: str  # ISO 8601, timezone-aware
    events: list[TrackedEvent] = field(default_factory=list)


@dataclass
class State:
    posts: dict[str, PostState] = field(default_factory=dict)
    last_heartbeat: str | None = None  # ISO 8601 of the last heartbeat notification

    def prune(self, now: datetime | None = None) -> None:
        """Drop posts not seen recently whose events have all ended."""
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=_PRUNE_AFTER_DAYS)
        for key in list(self.posts):
            post = self.posts[key]
            if datetime.fromisoformat(post.last_seen) >= cutoff:
                continue
            if all(datetime.fromisoformat(e.end) < now for e in post.events):
                del self.posts[key]


def load_state(path: Path) -> State:
    if not path.exists():
        return State()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        posts = {
            key: PostState(
                content_hash=p["content_hash"],
                last_seen=p["last_seen"],
                events=[
                    TrackedEvent(
                        event_key=e["event_key"],
                        google_event_id=e["google_event_id"],
                        end=e["end"],
                        summary=e.get("summary", ""),
                        start=e.get("start", ""),
                    )
                    for e in p.get("events", [])
                ],
            )
            for key, p in data.get("posts", {}).items()
        }
        return State(posts=posts, last_heartbeat=data.get("last_heartbeat"))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("State file %s is corrupt (%s); starting fresh", path, e)
        return State()


def save_state(state: State, path: Path) -> None:
    payload = {
        "version": STATE_VERSION,
        "last_heartbeat": state.last_heartbeat,
        "posts": {k: asdict(v) for k, v in state.posts.items()},
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
