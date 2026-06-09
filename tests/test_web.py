from datetime import UTC, datetime, timedelta

from ftmo_calendar.state import PostState, State, TrackedEvent
from ftmo_calendar.web import render_page

SNAPSHOT = {
    "ok": True,
    "last_run": "2026-06-09T12:00:00+00:00",
    "next_run": "2026-06-09T18:00:00+00:00",
    "last_error": None,
    "runs_ok": 4,
    "runs_failed": 0,
}


def state_with(events: list[TrackedEvent]) -> State:
    return State(
        posts={
            "p": PostState(content_hash="h", last_seen="2026-06-09T00:00:00+00:00", events=events)
        }
    )


def iso(delta_hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=delta_hours)).isoformat()


def test_upcoming_past_and_live_classification() -> None:
    events = [
        TrackedEvent("k1", "g1", end=iso(5), summary="Upcoming", start=iso(3)),
        TrackedEvent("k2", "g2", end=iso(1), summary="In progress", start=iso(-1)),
        TrackedEvent("k3", "g3", end=iso(-2), summary="Finished", start=iso(-4)),
    ]
    page = render_page(state_with(events), SNAPSHOT).decode("utf-8")
    assert '<tr class="soon"><td class="ev">Upcoming</td>' in page
    assert '<tr class="live"><td class="ev">In progress</td>' in page
    assert '<tr class="past"><td class="ev">Finished</td>' in page


def test_empty_state() -> None:
    page = render_page(State(), SNAPSHOT).decode("utf-8")
    assert "no events tracked yet" in page
    assert "OPERATIONAL" in page


def test_error_state_shown() -> None:
    snapshot = dict(SNAPSHOT, ok=False, last_error="token <expired>")
    page = render_page(State(), snapshot).decode("utf-8")
    assert "SYNC ERROR" in page
    assert "token &lt;expired&gt;" in page  # escaped


def test_dataless_events_skipped() -> None:
    page = render_page(
        state_with([TrackedEvent("k", "g", end="2026-06-10T00:00:00+00:00")]), SNAPSHOT
    ).decode("utf-8")
    assert "no events tracked yet" in page
