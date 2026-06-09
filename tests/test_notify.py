import pytest

from ftmo_calendar.config import NotifyConfig
from ftmo_calendar.notify.base import (
    format_error_message,
    format_heartbeat_message,
    format_run_message,
    notify_all,
)
from ftmo_calendar.notify.discord import DiscordNotifier
from ftmo_calendar.notify.factory import make_notifiers
from ftmo_calendar.notify.telegram import TelegramNotifier
from ftmo_calendar.pipeline import RunReport


def test_quiet_run_produces_no_message() -> None:
    report = RunReport(posts_seen=3, posts_relevant=2, posts_skipped_unchanged=2)
    assert format_run_message(report) is None


def test_run_message_lists_changes() -> None:
    report = RunReport(events_created=1, events_deleted=1)
    report.created_lines.append("⚠️ Maintenance — Sat 06 Jun 08:00–14:00")
    report.deleted_lines.append("⚠️ Maintenance — Sun 07 Jun (rescheduled)")
    text = format_run_message(report)
    assert text is not None
    assert "➕ ⚠️ Maintenance — Sat 06 Jun 08:00–14:00" in text
    assert "➖ ⚠️ Maintenance — Sun 07 Jun (rescheduled)" in text


def test_error_message_contains_cause_and_hint() -> None:
    text = format_error_message(RuntimeError("token refresh failed"))
    assert "token refresh failed" in text
    assert "❌" in text


def test_heartbeat_message() -> None:
    report = RunReport(posts_seen=2)
    assert "✅" in format_heartbeat_message(report)


def test_factory_with_no_channels() -> None:
    assert make_notifiers(NotifyConfig()) == []


def test_factory_selects_channels() -> None:
    cfg = NotifyConfig(
        discord_webhook_url="https://discord.com/api/webhooks/x",
        telegram_bot_token="123:abc",
        telegram_chat_id="42",
    )
    notifiers = make_notifiers(cfg)
    assert {type(n).__name__ for n in notifiers} == {"DiscordNotifier", "TelegramNotifier"}


def test_telegram_requires_both_token_and_chat_id() -> None:
    cfg = NotifyConfig(telegram_bot_token="123:abc")  # no chat id
    assert make_notifiers(cfg) == []


def test_notify_all_swallows_channel_failures(caplog: pytest.LogCaptureFixture) -> None:
    class Boom:
        name = "boom"

        def send(self, text: str) -> None:
            raise ConnectionError("webhook down")

    notify_all([Boom()], "hello")  # must not raise
    assert any("boom" in r.message for r in caplog.records)


def test_discord_posts_content(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    class FakeResponse:
        def raise_for_status(self) -> None: ...

    def fake_post(url, json=None, timeout=None):
        calls.update(url=url, json=json, timeout=timeout)
        return FakeResponse()

    import ftmo_calendar.notify.discord as discord_mod

    monkeypatch.setattr(discord_mod.requests, "post", fake_post)
    DiscordNotifier("https://discord.com/api/webhooks/x").send("hello")
    assert calls["url"] == "https://discord.com/api/webhooks/x"
    assert calls["json"] == {"content": "hello"}
    assert calls["timeout"] == 10


def test_telegram_posts_message(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    class FakeResponse:
        def raise_for_status(self) -> None: ...

    def fake_post(url, data=None, timeout=None):
        calls.update(url=url, data=data)
        return FakeResponse()

    import ftmo_calendar.notify.telegram as telegram_mod

    monkeypatch.setattr(telegram_mod.requests, "post", fake_post)
    TelegramNotifier("123:abc", "42").send("hello")
    assert calls["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert calls["data"] == {"chat_id": "42", "text": "hello"}
