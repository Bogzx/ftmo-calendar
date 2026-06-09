"""ICS (RFC 5545) feed generation.

The feed is a projection of the state file — regenerated wholesale after each
run. Anyone can subscribe to the resulting file/URL from Google, Apple, or
Outlook calendars without OAuth.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ftmo_calendar.state import State

logger = logging.getLogger(__name__)

_PRODID = "-//AutoFtmoCalendar//ftmo-calendar//EN"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    )


def _utc_stamp(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_ics(
    state: State, reminders_minutes: tuple[int, ...], now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    dtstamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:FTMO Trading Updates",
    ]
    for post in state.posts.values():
        for event in post.events:
            if not event.summary or not event.start:
                continue  # pre-v2 state entry without display data
            lines += [
                "BEGIN:VEVENT",
                f"UID:{event.event_key}@ftmo-calendar",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART:{_utc_stamp(event.start)}",
                f"DTEND:{_utc_stamp(event.end)}",
                f"SUMMARY:{_escape(event.summary)}",
            ]
            for minutes in reminders_minutes:
                lines += [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{_escape(event.summary)}",
                    f"TRIGGER:-PT{minutes}M",
                    "END:VALARM",
                ]
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics(
    state: State,
    path: Path,
    reminders_minutes: tuple[int, ...],
    now: datetime | None = None,
) -> None:
    content = render_ics(state, reminders_minutes, now=now)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8", newline="")
    tmp.replace(path)
    logger.info("ICS feed written to %s", path)
