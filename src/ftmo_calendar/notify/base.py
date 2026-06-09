"""Notification protocol and message formatting.

Notifications are best-effort: a failing channel is logged and never breaks a
run. The sync itself stays the source of truth; this is the visibility layer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol

from ftmo_calendar.pipeline import RunReport

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    name: str

    def send(self, text: str) -> None: ...


def notify_all(notifiers: Iterable[Notifier], text: str) -> None:
    for notifier in notifiers:
        try:
            notifier.send(text)
        except Exception as e:  # noqa: BLE001 - channel failure must not break the run
            logger.warning("Notification via %s failed: %s", notifier.name, e)


def format_run_message(report: RunReport) -> str | None:
    """Message describing calendar changes; None when nothing changed."""
    if not report.created_lines and not report.deleted_lines:
        return None
    lines = ["📅 FTMO Calendar updated"]
    lines.extend(f"➕ {line}" for line in report.created_lines)
    lines.extend(f"➖ {line}" for line in report.deleted_lines)
    return "\n".join(lines)


def format_error_message(error: BaseException) -> str:
    return (
        f"❌ ftmo-calendar run failed: {error}\n"
        "Check the logs; if it looks auth-related, run `ftmo-calendar auth --check`."
    )


def format_heartbeat_message(report: RunReport) -> str:
    return f"✅ ftmo-calendar alive — last check OK ({report.summary()})"
