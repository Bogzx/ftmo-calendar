"""Scraper for FTMO's trading-updates pages.

Verified structure (2026-06): the listing page embeds the newest post's full
text in `div.content.tu` under an `<h1>` like "Trading Update | Jun 4 2026",
and links older posts via `article.post-card` cards. Detail pages reuse the
same content container.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from ftmo_calendar.models import SourcePost

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_MONTHS = {
    name.lower(): i
    for i, names in enumerate(
        [
            ("Jan", "January"),
            ("Feb", "February"),
            ("Mar", "March"),
            ("Apr", "April"),
            ("May",),
            ("Jun", "June"),
            ("Jul", "July"),
            ("Aug", "August"),
            ("Sep", "September"),
            ("Oct", "October"),
            ("Nov", "November"),
            ("Dec", "December"),
        ],
        start=1,
    )
    for name in names
}

_DAY_FIRST = re.compile(r"(\d{1,2})[\s-]+([A-Za-z]{3,9})[\s-]+(\d{4})")
_MONTH_FIRST = re.compile(r"([A-Za-z]{3,9})[\s-]+(\d{1,2})[\s-]+(\d{4})")


class FetchError(Exception):
    """Network-level failure (transient; retried)."""


class ScrapeError(Exception):
    """Page fetched but the expected structure was missing."""


def parse_title_date(text: str) -> date | None:
    """Parse '28 May 2026', 'Jun 4 2026', or slug '...-28-may-2026' into a date."""
    m = _DAY_FIRST.search(text)
    if m and (month := _MONTHS.get(m.group(2).lower())):
        return date(int(m.group(3)), month, int(m.group(1)))
    m = _MONTH_FIRST.search(text)
    if m and (month := _MONTHS.get(m.group(1).lower())):
        return date(int(m.group(3)), month, int(m.group(2)))
    return None


def post_key_for(title: str, url: str) -> str:
    """Stable post identity. Prefer the date (title formats vary), else the URL slug."""
    parsed = parse_title_date(title) or parse_title_date(url.rstrip("/").rsplit("/", 1)[-1])
    if parsed:
        return f"trading-update-{parsed.isoformat()}"
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class FtmoSource:
    """Fetches and parses FTMO trading-update posts."""

    def __init__(
        self,
        url: str,
        *,
        max_posts: int = 4,
        max_age_days: int = 14,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.url = url
        self.max_posts = max_posts
        self.max_age_days = max_age_days
        self.timeout = timeout
        self.retries = retries
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def fetch(self) -> list[SourcePost]:
        """Return the embedded latest post plus recent linked posts, newest first."""
        embedded, links = self.parse_listing(self._get(self.url))
        posts: list[SourcePost] = [embedded] if embedded else []
        cutoff = date.today() - timedelta(days=self.max_age_days)
        for link in links:
            if len(posts) >= self.max_posts:
                break
            link_date = parse_title_date(link.rstrip("/").rsplit("/", 1)[-1])
            if link_date and link_date < cutoff:
                continue
            try:
                post = self.parse_post(self._get(link), link)
            except ScrapeError as e:
                logger.warning("Skipping post %s: %s", link, e)
                continue
            if embedded and post.post_key == embedded.post_key:
                continue
            posts.append(post)
        if not posts:
            raise ScrapeError(
                f"No trading-update posts found at {self.url} — "
                "the FTMO page structure may have changed"
            )
        return posts

    def parse_listing(self, html: str) -> tuple[SourcePost | None, list[str]]:
        soup = BeautifulSoup(html, "html.parser")
        embedded: SourcePost | None = None
        title_node = next(
            (h for h in soup.find_all("h1") if "trading update" in h.get_text().lower()),
            None,
        )
        content = soup.select_one("div.content.tu")
        if title_node and content:
            title = title_node.get_text(" ", strip=True)
            embedded = SourcePost(
                post_key=post_key_for(title, self.url),
                title=title,
                text=content.get_text(" ", strip=True),
                url=self.url,
            )
        else:
            logger.warning("No embedded post found on the listing page")

        links: list[str] = []
        for card in soup.select("article.post-card"):
            a = card.find("a", href=True)
            if a and "/blog/trading-updates/" in a["href"] and a["href"] not in links:
                links.append(a["href"])
        return embedded, links

    def parse_post(self, html: str, url: str) -> SourcePost:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.select_one("div.content.tu") or soup.select_one(
            "article, div.entry-content"
        )
        if content is None:
            raise ScrapeError(f"no content container found at {url}")
        title_node = soup.find("h1")
        title = title_node.get_text(" ", strip=True) if title_node else url
        return SourcePost(
            post_key=post_key_for(title, url),
            title=title,
            text=content.get_text(" ", strip=True),
            url=url,
        )

    def _get(self, url: str) -> str:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self._session.get(url, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise FetchError(f"HTTP {response.status_code} from {url}")
                response.raise_for_status()
                return response.text
            except (requests.RequestException, FetchError) as e:
                last = e
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s", attempt, self.retries, url, e
                )
                if attempt < self.retries:
                    time.sleep(2**attempt)
        raise FetchError(f"could not fetch {url} after {self.retries} attempts: {last}")
