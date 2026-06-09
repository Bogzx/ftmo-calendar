from datetime import date
from pathlib import Path

import pytest

from ftmo_calendar.sources.ftmo import (
    FtmoSource,
    ScrapeError,
    parse_title_date,
    post_key_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_title_date_day_first() -> None:
    assert parse_title_date("Trading Update | 28 May 2026") == date(2026, 5, 28)


def test_parse_title_date_month_first() -> None:
    assert parse_title_date("Trading Update | Jun 4 2026") == date(2026, 6, 4)


def test_parse_title_date_unparseable() -> None:
    assert parse_title_date("Hello world") is None


def test_post_key_is_format_independent() -> None:
    # The same post appears month-first when embedded, day-first on its detail page.
    a = post_key_for("Trading Update | Jun 4 2026", "https://ftmo.com/en/trading-updates/")
    b = post_key_for(
        "Trading Update | 4 Jun 2026",
        "https://ftmo.com/en/blog/trading-updates/trading-update-4-jun-2026/",
    )
    assert a == b == "trading-update-2026-06-04"


def test_post_key_falls_back_to_slug() -> None:
    key = post_key_for("No date here", "https://ftmo.com/en/blog/trading-updates/some-slug/")
    assert key == "some-slug"


def test_parse_listing_extracts_embedded_post_and_links() -> None:
    src = FtmoSource("https://ftmo.com/en/trading-updates/")
    post, links = src.parse_listing((FIXTURES / "listing.html").read_text(encoding="utf-8"))
    assert post is not None
    assert post.post_key == "trading-update-2026-06-04"
    assert "Weekend Maintenance" in post.text
    assert "GMT+3" in post.text
    assert links == [
        "https://ftmo.com/en/blog/trading-updates/trading-update-28-may-2026/",
        "https://ftmo.com/en/blog/trading-updates/trading-update-21-may-2026/",
    ]


def test_parse_post_extracts_detail_page() -> None:
    src = FtmoSource("https://ftmo.com/en/trading-updates/")
    url = "https://ftmo.com/en/blog/trading-updates/trading-update-28-may-2026/"
    post = src.parse_post((FIXTURES / "post.html").read_text(encoding="utf-8"), url)
    assert post.post_key == "trading-update-2026-05-28"
    assert "crypto market is closed" in post.text.lower()
    assert post.url == url


def test_parse_post_raises_on_missing_container() -> None:
    src = FtmoSource("https://ftmo.com/en/trading-updates/")
    with pytest.raises(ScrapeError):
        src.parse_post("<html><body><p>nothing</p></body></html>", "https://x/")
