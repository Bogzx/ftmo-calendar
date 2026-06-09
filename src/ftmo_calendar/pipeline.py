"""Orchestration: fetch → cache-check → extract → validate → reconcile."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from ftmo_calendar.config import AppConfig
from ftmo_calendar.models import SourcePost, TradingEvent
from ftmo_calendar.parsing.llm import RawEvent
from ftmo_calendar.parsing.validate import validate_events
from ftmo_calendar.sinks.base import EventSink
from ftmo_calendar.state import PostState, State, TrackedEvent

logger = logging.getLogger(__name__)


class Source(Protocol):
    def fetch(self) -> list[SourcePost]: ...


class Extractor(Protocol):
    def extract(self, text: str) -> list[RawEvent]: ...


@dataclass
class RunReport:
    posts_seen: int = 0
    posts_relevant: int = 0
    posts_skipped_unchanged: int = 0
    events_created: int = 0
    events_deleted: int = 0
    events_kept: int = 0
    rejections: int = 0
    dry_run: bool = False

    def summary(self) -> str:
        prefix = "[dry-run] " if self.dry_run else ""
        return (
            f"{prefix}posts: {self.posts_seen} seen, {self.posts_relevant} relevant, "
            f"{self.posts_skipped_unchanged} unchanged | events: {self.events_created} created, "
            f"{self.events_deleted} removed, {self.events_kept} kept, "
            f"{self.rejections} rejected extractions"
        )


def run_pipeline(
    *,
    source: Source,
    extractor: Extractor,
    sink: EventSink,
    state: State,
    config: AppConfig,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RunReport:
    now = now or datetime.now(timezone.utc)
    report = RunReport(dry_run=dry_run)
    source_tz = ZoneInfo(config.source.timezone)
    calendar_tz = ZoneInfo(config.calendar.timezone)

    posts = source.fetch()
    report.posts_seen = len(posts)

    for post in posts:
        post_state = state.posts.get(post.post_key)
        if post_state is not None and not dry_run:
            post_state.last_seen = now.isoformat()

        if not _is_relevant(post, config.source.keywords):
            logger.info("Post %s has no relevant keywords; skipping", post.post_key)
            continue
        report.posts_relevant += 1

        if post_state is not None and post_state.content_hash == post.content_hash:
            logger.info("Post %s unchanged; skipping LLM call", post.post_key)
            report.posts_skipped_unchanged += 1
            continue

        logger.info("Post %s is new or changed; extracting events", post.post_key)
        raw_events = extractor.extract(post.text)
        events, rejections = validate_events(
            raw_events, post, config.events, source_tz, calendar_tz, now=now
        )
        report.rejections += len(rejections)
        for rejection in rejections:
            logger.warning("Rejected extraction for %s: %s", post.post_key, rejection.reason)

        new_post_state = _reconcile(post, events, post_state, sink, report, dry_run, now)
        if not dry_run:
            state.posts[post.post_key] = new_post_state

    if not dry_run:
        state.prune(now=now)
    return report


def _is_relevant(post: SourcePost, keywords: tuple[str, ...]) -> bool:
    text = post.text.lower()
    return any(k.strip().lower() in text for k in keywords if k.strip())


def _reconcile(
    post: SourcePost,
    events: list[TradingEvent],
    post_state: PostState | None,
    sink: EventSink,
    report: RunReport,
    dry_run: bool,
    now: datetime,
) -> PostState:
    old = {e.event_key: e for e in (post_state.events if post_state else [])}
    new_keys = {e.event_key for e in events}
    tracked: list[TrackedEvent] = []

    for key, old_event in old.items():
        if key in new_keys:
            continue
        if datetime.fromisoformat(old_event.end) <= now:
            tracked.append(old_event)  # it happened; preserve calendar history
            continue
        logger.info("Announcement changed: removing stale event %s", key)
        if not dry_run:
            sink.delete_event(old_event.google_event_id)
        report.events_deleted += 1

    for event in events:
        if event.event_key in old:
            tracked.append(old[event.event_key])
            report.events_kept += 1
            continue
        if dry_run:
            logger.info("[dry-run] would create '%s' at %s", event.summary, event.start)
            report.events_created += 1
            continue
        existing_id = sink.find_event_id_by_key(event.event_key)
        if existing_id:
            logger.info("Event %s already in calendar; adopting it", event.event_key)
            tracked.append(TrackedEvent(event.event_key, existing_id, event.end.isoformat()))
            report.events_kept += 1
            continue
        google_id = sink.create_event(event)
        tracked.append(TrackedEvent(event.event_key, google_id, event.end.isoformat()))
        report.events_created += 1

    return PostState(content_hash=post.content_hash, last_seen=now.isoformat(), events=tracked)
