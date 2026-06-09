import json
import threading
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ftmo_calendar.server import ServerStatus, make_handler, run_sync_loop
from ftmo_calendar.sinks.ics import write_ics
from ftmo_calendar.state import PostState, State, TrackedEvent, save_state

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
                        summary="FTMO Platform Maintenance",
                        start="2026-06-06T08:00:00+03:00",
                    )
                ],
            )
        }
    )


@pytest.fixture
def server(tmp_path: Path):
    state = make_state()
    state_path = tmp_path / "state.json"
    save_state(state, state_path)
    ics_path = tmp_path / "feed.ics"
    write_ics(state, ics_path, (60,), now=NOW)

    status = ServerStatus(started_at=NOW.isoformat())
    handler = make_handler(ics_path=ics_path, state_path=state_path, status=status)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, status, ics_path
    httpd.shutdown()


def get(url: str):
    try:
        response = urllib.request.urlopen(url, timeout=5)
        return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def test_healthz(server) -> None:
    base, status, _ = server
    status.record_success(now=NOW)
    code, ctype, body = get(f"{base}/healthz")
    assert code == 200 and "application/json" in ctype
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["runs_ok"] == 1
    assert payload["last_run"] == NOW.isoformat()


def test_healthz_reports_failure(server) -> None:
    base, status, _ = server
    status.record_failure(RuntimeError("boom"), now=NOW)
    payload = json.loads(get(f"{base}/healthz")[2])
    assert payload["ok"] is False
    assert "boom" in payload["last_error"]


def test_feed_served_as_calendar(server) -> None:
    base, _, _ = server
    code, ctype, body = get(f"{base}/feed.ics")
    assert code == 200
    assert "text/calendar" in ctype
    assert b"BEGIN:VCALENDAR" in body


def test_feed_404_when_missing(server) -> None:
    base, _, ics_path = server
    ics_path.unlink()
    code, _, _ = get(f"{base}/feed.ics")
    assert code == 404


def test_status_page_lists_events(server) -> None:
    base, _, _ = server
    code, ctype, body = get(f"{base}/status")
    assert code == 200 and "text/html" in ctype
    assert b"FTMO Platform Maintenance" in body


def test_unknown_path_404(server) -> None:
    assert get(f"{server[0]}/nope")[0] == 404


def test_sync_loop_runs_and_records() -> None:
    status = ServerStatus(started_at=NOW.isoformat())
    stop = threading.Event()
    calls = []

    def sync() -> None:
        calls.append(1)
        if len(calls) >= 3:
            stop.set()

    run_sync_loop(sync, interval_seconds=0.01, stop=stop, status=status)
    assert len(calls) == 3
    assert status.snapshot()["runs_ok"] == 3


def test_sync_loop_records_failure_and_continues() -> None:
    status = ServerStatus(started_at=NOW.isoformat())
    stop = threading.Event()
    errors = []
    calls = []

    def sync() -> None:
        calls.append(1)
        if len(calls) >= 2:
            stop.set()
        raise RuntimeError("scrape failed")

    run_sync_loop(
        sync, interval_seconds=0.01, stop=stop, status=status, on_error=errors.append
    )
    assert len(calls) == 2
    snapshot = status.snapshot()
    assert snapshot["runs_failed"] == 2
    assert "scrape failed" in snapshot["last_error"]
    assert len(errors) == 2
