"""Convert raw LLM extractions into validated, timezone-aware TradingEvents."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ftmo_calendar.config import EventRules
from ftmo_calendar.models import EventType, SourcePost, TradingEvent
from ftmo_calendar.parsing.llm import RawEvent

logger = logging.getLogger(__name__)

_OFFSET = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2}):?(\d{2})?$")
_EXCERPT_LIMIT = 800


@dataclass(frozen=True)
class Rejection:
    raw: RawEvent
    reason: str


def _offset_tz(stated: str) -> timezone | None:
    m = _OFFSET.match(stated.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours, minutes = int(m.group(2)), int(m.group(3) or 0)
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def build_description(post: SourcePost) -> str:
    excerpt = post.text[:_EXCERPT_LIMIT]
    if len(post.text) > _EXCERPT_LIMIT:
        excerpt += "…"
    return f"{excerpt}\n\nSource: {post.url}\nCreated by AutoFtmoCalendar"


def validate_events(
    raw_events: list[RawEvent],
    post: SourcePost,
    rules: EventRules,
    source_tz: ZoneInfo,
    calendar_tz: ZoneInfo,
    now: datetime | None = None,
) -> tuple[list[TradingEvent], list[Rejection]]:
    now = now or datetime.now(UTC)
    events: list[TradingEvent] = []
    rejections: list[Rejection] = []

    for raw in raw_events:
        try:
            start = datetime.fromisoformat(raw.start_time)
            end = datetime.fromisoformat(raw.end_time)
        except ValueError as e:
            rejections.append(Rejection(raw, f"unparseable datetime: {e}"))
            continue

        stated = _offset_tz(raw.stated_utc_offset) if raw.stated_utc_offset else None
        if start.tzinfo is None:
            start = start.replace(tzinfo=stated or source_tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=stated or source_tz)

        if end <= start:
            rejections.append(Rejection(raw, "end is not after start"))
        elif end - start > timedelta(hours=rules.max_duration_hours):
            rejections.append(
                Rejection(raw, f"duration exceeds {rules.max_duration_hours}h sanity cap")
            )
        elif start > now + timedelta(days=rules.max_days_ahead):
            rejections.append(Rejection(raw, "too far in the future"))
        elif end <= now:
            rejections.append(Rejection(raw, "already ended"))
        else:
            event_type = EventType(raw.event_type)
            events.append(
                TradingEvent(
                    event_type=event_type,
                    summary=rules.summaries.get(event_type.value, rules.summaries["other"]),
                    description=build_description(post),
                    start=start.astimezone(calendar_tz),
                    end=end.astimezone(calendar_tz),
                    source_post_key=post.post_key,
                    source_url=post.url,
                )
            )
    return events, rejections
