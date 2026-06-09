from datetime import UTC, datetime
from pathlib import Path

from ftmo_calendar.sinks.ics import render_ics, write_ics
from ftmo_calendar.state import PostState, State, TrackedEvent

NOW = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)


def make_state() -> State:
    return State(
        posts={
            "p1": PostState(
                content_hash="h",
                last_seen="2026-06-09T00:00:00+00:00",
                events=[
                    TrackedEvent(
                        event_key="abc123",
                        google_event_id="g1",
                        end="2026-06-06T14:00:00+03:00",
                        summary="⚠️ FTMO Platform Maintenance",
                        start="2026-06-06T08:00:00+03:00",
                        event_type="maintenance",
                    ),
                    # v1-era event without display data — must be skipped
                    TrackedEvent(
                        event_key="old", google_event_id="g2", end="2026-06-07T00:00:00+00:00"
                    ),
                ],
            )
        }
    )


def test_calendar_envelope_and_event() -> None:
    ics = render_ics(make_state(), (60, 10), now=NOW)
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "VERSION:2.0" in ics
    assert ics.count("BEGIN:VEVENT") == 1  # the dataless event is skipped
    assert "UID:abc123@ftmo-calendar" in ics


def test_times_converted_to_utc() -> None:
    ics = render_ics(make_state(), (), now=NOW)
    assert "DTSTART:20260606T050000Z" in ics  # 08:00+03:00 -> 05:00Z
    assert "DTEND:20260606T110000Z" in ics


def test_valarm_per_reminder() -> None:
    ics = render_ics(make_state(), (60, 10), now=NOW)
    assert ics.count("BEGIN:VALARM") == 2
    assert "TRIGGER:-PT60M" in ics and "TRIGGER:-PT10M" in ics


def test_summary_escaped() -> None:
    state = make_state()
    state.posts["p1"].events[0].summary = "Closed; markets, a\\b"
    ics = render_ics(state, (), now=NOW)
    assert "SUMMARY:Closed\\; markets\\, a\\\\b" in ics


def test_crlf_line_endings() -> None:
    ics = render_ics(make_state(), (), now=NOW)
    assert "\n" not in ics.replace("\r\n", "")


def test_write_ics(tmp_path: Path) -> None:
    path = tmp_path / "feed.ics"
    write_ics(make_state(), path, (60,), now=NOW)
    assert path.read_text(encoding="utf-8").startswith("BEGIN:VCALENDAR")


def test_refresh_hints_for_subscribers() -> None:
    ics = render_ics(make_state(), (), refresh_minutes=360, now=NOW)
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT360M" in ics
    assert "X-PUBLISHED-TTL:PT360M" in ics


def test_no_refresh_hints_by_default() -> None:
    ics = render_ics(make_state(), (), now=NOW)
    assert "REFRESH-INTERVAL" not in ics


def test_description_with_source_url() -> None:
    ics = render_ics(make_state(), (), source_url="https://ftmo.com/en/trading-updates/", now=NOW)
    assert "DESCRIPTION:Source: https://ftmo.com/en/trading-updates/" in ics
    assert "AutoFtmoCalendar" in ics


def crypto_event() -> TrackedEvent:
    return TrackedEvent(
        event_key="cr1",
        google_event_id="g3",
        end="2026-06-07T12:00:00+03:00",
        summary="🚫 Crypto Market Closed",
        start="2026-06-07T10:00:00+03:00",
        event_type="crypto_closure",
    )


def test_types_filter_includes_only_matching_events() -> None:
    state = make_state()
    state.posts["p1"].events.append(crypto_event())
    ics = render_ics(state, (), types=frozenset({"crypto_closure"}), now=NOW)
    assert ics.count("BEGIN:VEVENT") == 1
    assert "Crypto Market Closed" in ics
    assert "Platform Maintenance" not in ics


def test_no_types_filter_includes_everything() -> None:
    state = make_state()
    state.posts["p1"].events.append(crypto_event())
    ics = render_ics(state, (), now=NOW)
    assert ics.count("BEGIN:VEVENT") == 2


def test_typeless_legacy_events_appear_only_unfiltered() -> None:
    state = make_state()
    state.posts["p1"].events[0].event_type = ""  # pre-v3 entry
    assert render_ics(state, (), now=NOW).count("BEGIN:VEVENT") == 1
    filtered = render_ics(state, (), types=frozenset({"maintenance"}), now=NOW)
    assert filtered.count("BEGIN:VEVENT") == 0


def test_filtered_calendar_is_named_after_filter() -> None:
    ics = render_ics(make_state(), (), types=frozenset({"maintenance"}), now=NOW)
    assert "X-WR-CALNAME:FTMO Trading Updates (maintenance)" in ics
