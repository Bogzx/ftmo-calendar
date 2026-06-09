"""Command-line interface: ftmo-calendar run|auth|status."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from ftmo_calendar import __version__
from ftmo_calendar.config import AppConfig, ConfigError, load_config
from ftmo_calendar.notify.base import (
    Notifier,
    format_error_message,
    format_heartbeat_message,
    format_run_message,
    notify_all,
)
from ftmo_calendar.notify.factory import make_notifiers
from ftmo_calendar.pipeline import RunReport
from ftmo_calendar.state import State

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftmo-calendar",
        description="Sync FTMO trading updates (maintenance, closures) to Google Calendar.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="path to config.toml (default: ./config.toml)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="check FTMO and sync the calendar (default)")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show planned changes without touching the calendar or state",
    )

    auth_parser = subparsers.add_parser("auth", help="interactive Google OAuth authorization")
    auth_parser.add_argument(
        "--check", action="store_true", help="report credential status without authorizing"
    )

    subparsers.add_parser("status", help="show tracked posts and events from the last runs")
    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stderr,
    )


def _notify_run_outcome(
    config: AppConfig,
    notifiers: list[Notifier],
    report: RunReport,
    state: State,
    now: datetime | None = None,
) -> None:
    """Send the change message and, when due, a heartbeat; stamps the heartbeat in state."""
    if config.notify.on_events:
        message = format_run_message(report)
        if message:
            notify_all(notifiers, message)
    hours = config.notify.heartbeat_hours
    if not hours or not notifiers:
        return
    now = now or datetime.now(UTC)
    last = state.last_heartbeat
    if last is not None and now - datetime.fromisoformat(last) < timedelta(hours=hours):
        return
    notify_all(notifiers, format_heartbeat_message(report))
    state.last_heartbeat = now.isoformat()


def _cmd_run(config: AppConfig, dry_run: bool) -> int:
    from ftmo_calendar.parsing.factory import make_backend
    from ftmo_calendar.parsing.llm import EventExtractor
    from ftmo_calendar.pipeline import run_pipeline
    from ftmo_calendar.sinks.auth import load_credentials
    from ftmo_calendar.sinks.google_calendar import GoogleCalendarSink
    from ftmo_calendar.sources.ftmo import FtmoSource
    from ftmo_calendar.state import load_state, save_state

    source = FtmoSource(
        config.source.url,
        max_posts=config.source.max_posts,
        max_age_days=config.source.max_age_days,
    )
    extractor = EventExtractor(make_backend(config.llm), config.llm.models)
    credentials = load_credentials(config.calendar, config.base_dir)
    sink = GoogleCalendarSink(credentials, config.calendar)
    state = load_state(config.state_path)

    report = run_pipeline(
        source=source,
        extractor=extractor,
        sink=sink,
        state=state,
        config=config,
        dry_run=dry_run,
    )
    if not dry_run:
        _notify_run_outcome(config, make_notifiers(config.notify), report, state)
        save_state(state, config.state_path)
        if config.ics.enabled:
            from ftmo_calendar.sinks.ics import write_ics

            write_ics(state, config.resolve(config.ics.path), config.calendar.reminders_minutes)
    print(report.summary())
    return EXIT_OK


def _cmd_auth(config: AppConfig, check: bool) -> int:
    from ftmo_calendar.sinks.auth import describe_credentials, interactive_auth

    if check:
        print(describe_credentials(config.calendar, config.base_dir))
        return EXIT_OK
    if config.calendar.auth_mode == "service_account":
        print("auth_mode is 'service_account' — no interactive authorization needed.")
        print(describe_credentials(config.calendar, config.base_dir))
        return EXIT_OK
    token_path = interactive_auth(config.calendar, config.base_dir)
    print(f"Authorized. Token saved to {token_path}.")
    return EXIT_OK


def _cmd_status(config: AppConfig) -> int:
    from ftmo_calendar.state import load_state

    state = load_state(config.state_path)
    if not state.posts:
        print("No runs recorded yet (state file empty or missing).")
        return EXIT_OK
    print(f"Tracked posts ({len(state.posts)}):")
    for key, post in sorted(state.posts.items(), reverse=True):
        print(f"  {key}  last seen {post.last_seen}  events: {len(post.events)}")
        for event in post.events:
            print(f"    - {event.event_key}  ends {event.end}  (google id {event.google_event_id})")
    return EXIT_OK


def _force_utf8_streams() -> None:
    """Event summaries contain emoji; Windows pipes default to cp1252 and would crash."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    config_path: Path = args.config
    load_dotenv(config_path.resolve().parent / ".env")

    try:
        config = load_config(config_path)
    except ConfigError as e:
        logger.error("Configuration error: %s", e)
        return EXIT_CONFIG

    from ftmo_calendar.sinks.auth import AuthError

    command = args.command or "run"
    try:
        if command == "run":
            return _cmd_run(config, dry_run=getattr(args, "dry_run", False))
        if command == "auth":
            return _cmd_auth(config, check=args.check)
        return _cmd_status(config)
    except (AuthError, ConfigError) as e:
        logger.error("%s", e)
        _notify_failure(config, command, e)
        return EXIT_CONFIG
    except Exception as e:
        logger.exception("Run failed")
        _notify_failure(config, command, e)
        return EXIT_ERROR


def _notify_failure(config: AppConfig, command: str, error: BaseException) -> None:
    """The tool's core promise: it never fails silently. Only `run` failures alert."""
    if command == "run" and config.notify.on_errors:
        notify_all(make_notifiers(config.notify), format_error_message(error))


def entry() -> None:
    sys.exit(main())
