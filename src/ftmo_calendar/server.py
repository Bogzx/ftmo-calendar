"""Hosted mode: periodic sync loop + HTTP server exposing the ICS feed.

One person runs `ftmo-calendar serve` (or the Docker container); any trader
subscribes to `http://host:port/feed.ics` from Google/Apple/Outlook calendar —
no OAuth, no API keys on the subscriber side.

Endpoints: GET /feed.ics (the calendar), GET /status (HTML), GET /healthz (JSON).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ftmo_calendar.state import load_state
from ftmo_calendar.stats import StatsStore

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
    ics_path: Path,
    state_path: Path,
    status: ServerStatus,
    feed_renderer: Callable[[frozenset[str]], bytes] | None = None,
    stats: StatsStore | None = None,
) -> type[BaseHTTPRequestHandler]:
    from ftmo_calendar.models import EventType

    valid_types = {t.value for t in EventType}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            logger.debug("http: " + format, *args)

        def _respond(
            self,
            code: int,
            content_type: str,
            body: bytes,
            extra_headers: list[tuple[str, str]] | None = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in extra_headers or []:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _cookie(self, name: str) -> str:
            jar = SimpleCookie()
            jar.load(self.headers.get("Cookie", ""))
            morsel = jar.get(name)
            return morsel.value if morsel else ""

        def _client_hash(self) -> str:
            raw = f"{self.client_address[0]}|{self.headers.get('User-Agent', '')}"
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

        def _json(self, code: int, payload: dict) -> None:
            self._respond(code, "application/json; charset=utf-8", json.dumps(payload).encode())

        def _serve_feed(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            types_param = query.get("types", [""])[0]
            if types_param and feed_renderer is not None:
                requested = frozenset(t.strip() for t in types_param.split(",") if t.strip())
                unknown = requested - valid_types
                if unknown or not requested:
                    self._json(
                        400,
                        {
                            "error": f"unknown types: {sorted(unknown)}",
                            "valid": sorted(valid_types),
                        },
                    )
                    return
                self._respond(200, "text/calendar; charset=utf-8", feed_renderer(requested))
                return
            if not ics_path.exists():
                self._json(404, {"error": "feed not generated yet"})
                return
            self._respond(200, "text/calendar; charset=utf-8", ics_path.read_bytes())

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, status.snapshot())
            elif path == "/stats":
                if stats is None:
                    self._json(404, {"error": "stats not enabled"})
                else:
                    self._json(200, stats.snapshot())
            elif path == "/feed.ics":
                if stats is not None:
                    stats.record_feed_hit(self._client_hash())
                self._serve_feed()
            elif path in ("/", "/status"):
                from ftmo_calendar.web import render_page

                extra_headers: list[tuple[str, str]] = []
                stats_snapshot = None
                if stats is not None:
                    visitor_id = self._cookie("aftc_id")
                    if not visitor_id:
                        visitor_id = secrets.token_hex(8)
                        extra_headers.append(
                            (
                                "Set-Cookie",
                                f"aftc_id={visitor_id}; Max-Age=31536000; Path=/; "
                                "SameSite=Lax; HttpOnly",
                            )
                        )
                    stats.record_page_view(visitor_id)
                    stats_snapshot = stats.snapshot()
                body = render_page(load_state(state_path), status.snapshot(), stats_snapshot)
                self._respond(200, "text/html; charset=utf-8", body, extra_headers)
            else:
                self._json(404, {"error": "not found"})

    return Handler


def serve_forever(
    host: str,
    port: int,
    interval_seconds: float,
    ics_path: Path,
    state_path: Path,
    sync_fn: Callable[[], None],
    on_error: Callable[[BaseException], None] | None = None,
    feed_renderer: Callable[[frozenset[str]], bytes] | None = None,
    stats: StatsStore | None = None,
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
    httpd = ThreadingHTTPServer(
        (host, port), make_handler(ics_path, state_path, status, feed_renderer, stats)
    )
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
