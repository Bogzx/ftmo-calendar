"""Hosted mode: periodic sync loop + HTTP server exposing the ICS feed.

One person runs `ftmo-calendar serve` (or the Docker container); any trader
subscribes to `http://host:port/feed.ics` from Google/Apple/Outlook calendar —
no OAuth, no API keys on the subscriber side.

Endpoints: GET /feed.ics (the calendar), GET /status (HTML), GET /healthz (JSON).
"""

from __future__ import annotations

import html
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ftmo_calendar.state import load_state

logger = logging.getLogger(__name__)


@dataclass
class ServerStatus:
    """Thread-safe record of how the background sync is doing."""

    started_at: str
    interval_seconds: float = 0
    last_run: str | None = None
    last_error: str | None = None
    runs_ok: int = 0
    runs_failed: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self, now: datetime | None = None) -> None:
        with self._lock:
            self.last_run = (now or datetime.now(UTC)).isoformat()
            self.last_error = None
            self.runs_ok += 1

    def record_failure(self, error: BaseException, now: datetime | None = None) -> None:
        with self._lock:
            self.last_run = (now or datetime.now(UTC)).isoformat()
            self.last_error = str(error)
            self.runs_failed += 1

    def snapshot(self) -> dict:
        with self._lock:
            next_run = None
            if self.last_run and self.interval_seconds:
                next_dt = datetime.fromisoformat(self.last_run) + timedelta(
                    seconds=self.interval_seconds
                )
                next_run = next_dt.isoformat()
            return {
                "ok": self.last_error is None,
                "started_at": self.started_at,
                "last_run": self.last_run,
                "next_run": next_run,
                "last_error": self.last_error,
                "runs_ok": self.runs_ok,
                "runs_failed": self.runs_failed,
            }


def run_sync_loop(
    sync_fn: Callable[[], None],
    interval_seconds: float,
    stop: threading.Event,
    status: ServerStatus,
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Run sync_fn immediately and then every interval until stop is set.

    A failing sync is recorded and reported but never kills the loop — the
    feed keeps serving the last good data. A persistent identical error is
    notified once, not every interval; a success resets the dedup so a
    recurring flap still alerts.
    """
    last_notified_error: str | None = None
    while not stop.is_set():
        try:
            sync_fn()
            status.record_success()
            last_notified_error = None
        except Exception as e:  # noqa: BLE001 - loop must survive any sync failure
            logger.exception("Scheduled sync failed")
            status.record_failure(e)
            if on_error is not None and str(e) != last_notified_error:
                last_notified_error = str(e)
                try:
                    on_error(e)
                except Exception:  # noqa: BLE001
                    logger.warning("Error notification failed", exc_info=True)
        if stop.wait(interval_seconds):
            break


def make_handler(
    ics_path: Path, state_path: Path, status: ServerStatus
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            logger.debug("http: " + format, *args)

        def _respond(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict) -> None:
            self._respond(code, "application/json; charset=utf-8", json.dumps(payload).encode())

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, status.snapshot())
            elif path == "/feed.ics":
                if not ics_path.exists():
                    self._json(404, {"error": "feed not generated yet"})
                    return
                self._respond(
                    200,
                    "text/calendar; charset=utf-8",
                    ics_path.read_bytes(),
                )
            elif path in ("/", "/status"):
                self._respond(200, "text/html; charset=utf-8", _status_page(state_path, status))
            else:
                self._json(404, {"error": "not found"})

    return Handler


def _next_event_line(state) -> str:  # noqa: ANN001
    now = datetime.now(UTC)
    upcoming = []
    for post in state.posts.values():
        for event in post.events:
            if not event.start or not event.summary:
                continue
            try:
                start = datetime.fromisoformat(event.start)
            except ValueError:
                continue
            if start > now:
                upcoming.append((start, event.summary))
    if not upcoming:
        return "none scheduled"
    start, summary = min(upcoming)
    return f"{html.escape(summary)} — {start:%a %d %b %H:%M %Z}"


def _status_page(state_path: Path, status: ServerStatus) -> bytes:
    snapshot = status.snapshot()
    state = load_state(state_path)
    rows = []
    for post_key, post in sorted(state.posts.items(), reverse=True):
        for event in post.events:
            rows.append(
                f"<tr><td>{html.escape(event.summary or event.event_key)}</td>"
                f"<td>{html.escape(event.start)}</td><td>{html.escape(event.end)}</td>"
                f"<td>{html.escape(post_key)}</td></tr>"
            )
    health = "🟢 healthy" if snapshot["ok"] else f"🔴 {html.escape(snapshot['last_error'] or '')}"
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>FTMO Trading Calendar</title>
<style>body{{font-family:system-ui,sans-serif;max-width:48rem;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:.4rem;text-align:left}}
code{{background:#f4f4f4;padding:.1rem .3rem}}
.next{{font-size:1.1rem;background:#fff8e1;border:1px solid #f0d000;border-radius:.5rem;padding:.8rem}}</style>
</head><body>
<h1>FTMO Trading Calendar</h1>
<p class="next"><strong>Next event:</strong> {_next_event_line(state)}</p>
<p>Status: {health}</p>
<p>Last sync: {html.escape(snapshot["last_run"] or "never")} ·
next: {html.escape(snapshot["next_run"] or "–")} ·
ok: {snapshot["runs_ok"]} · failed: {snapshot["runs_failed"]}</p>
<h2>Subscribe (free, no account needed)</h2>
<p>Add this server's feed to your own calendar — it stays in sync automatically:</p>
<ul>
<li><strong>Google Calendar:</strong> Other calendars → <em>+</em> → <em>From URL</em> →
paste <code>https://&lt;this-host&gt;/feed.ics</code></li>
<li><strong>Apple Calendar:</strong> File → <em>New Calendar Subscription…</em> → paste the URL</li>
<li><strong>Outlook:</strong> Add calendar → <em>Subscribe from web</em> → paste the URL</li>
</ul>
<h2>Tracked events</h2>
<table><tr><th>Event</th><th>Start</th><th>End</th><th>Source post</th></tr>
{"".join(rows) or '<tr><td colspan="4">none yet</td></tr>'}
</table></body></html>"""
    return page.encode("utf-8")


def serve_forever(
    host: str,
    port: int,
    interval_seconds: float,
    ics_path: Path,
    state_path: Path,
    sync_fn: Callable[[], None],
    on_error: Callable[[BaseException], None] | None = None,
) -> int:
    status = ServerStatus(
        started_at=datetime.now(UTC).isoformat(), interval_seconds=interval_seconds
    )
    stop = threading.Event()
    loop_thread = threading.Thread(
        target=run_sync_loop,
        args=(sync_fn, interval_seconds, stop, status, on_error),
        daemon=True,
        name="sync-loop",
    )
    loop_thread.start()
    httpd = ThreadingHTTPServer((host, port), make_handler(ics_path, state_path, status))
    logger.info(
        "Serving on http://%s:%d (feed: /feed.ics, status: /status); sync every %.0f min",
        host,
        port,
        interval_seconds / 60,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        stop.set()
        httpd.server_close()
    return 0
