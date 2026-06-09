# Phase 1: Trustworthy Sync Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild AutoFtmoCalendar as a professional, tested Python package (`ftmo-calendar`) that reliably syncs FTMO trading updates to Google Calendar with provider-agnostic LLM parsing, reconcile-based sync, and hardened auth.

**Architecture:** src-layout package with a `Source → Extractor → Validate → Reconcile → Sink` pipeline. State (post content hashes + created event IDs) persists in `state.json`. Google events carry an `aftc_key` extended property for state-loss-proof dedup. LLM access goes through an `LLMBackend` protocol with `gemini` and `openai-compatible` (OpenRouter/OpenAI/Groq/Ollama) backends.

**Tech Stack:** Python ≥3.11, requests, BeautifulSoup4, pydantic v2, google-api-python-client, google-auth(-oauthlib), google-genai, openai, pytest, ruff, mypy, GitHub Actions.

**Verified facts about the FTMO site (checked 2026-06-09):**
- `https://ftmo.com/en/trading-updates/` returns HTTP 200 to plain requests with a Chrome UA (no JS needed).
- The old `div.trup-primary` container **no longer exists** — the current scraper is broken.
- The listing page embeds the latest post: an `<h1 class="h2">Trading Update | Jun 4 2026</h1>` followed by `<div class="content js-definition-point-for-toc-section tu">…</div>` containing `wp-block-heading` sections ("Weekend Maintenance", "King's Birthday Holiday", …).
- Older posts appear as `<article class="post-card …">` cards whose first `<a href>` points to `https://ftmo.com/en/blog/trading-updates/trading-update-28-may-2026/`.
- Detail pages use the **same** `div.content…tu` container and an `<h1>` title like "Trading Update | 28 May 2026".
- Title date formats vary: "28 May 2026" (day-first) on detail pages, "Jun 4 2026" (month-first) on the embedded listing post. Post keys must normalize via parsed date.
- Post text states the timezone as "GMT+3".

---

### Task 1: Secret hygiene & repo cleanup

**Files:**
- Modify: `.gitignore`
- Delete (untrack): `app.log`
- Delete: `check_models.py`, `test_generation.py`

- [ ] **Step 1: Untrack app.log and delete dev scraps**

```powershell
git rm --cached app.log
git rm check_models.py test_generation.py
```

- [ ] **Step 2: Extend .gitignore**

Read the existing `.gitignore` first, then ensure it contains (append missing lines):

```gitignore
# Secrets & runtime artifacts
.env
credentials.json
token.json
service_account.json
app.log
*.log
state.json

# Python
__pycache__/
*.py[cod]
.venv/
venv/
dist/
build/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

- [ ] **Step 3: Check history for other secrets**

```powershell
git log --all --oneline -- credentials.json token.json .env service_account.json
```

Expected: no output (only `app.log` was ever committed). If output appears, add those paths to the filter-repo step below.

- [ ] **Step 4: Commit the cleanup**

```powershell
git add -A; git commit -m "chore: untrack app.log, remove dev scraps, harden .gitignore"
```

- [ ] **Step 5: Purge app.log from git history and force-push**

The committed `app.log` contains an OAuth authorization code. Purge it:

```powershell
pip install git-filter-repo
git filter-repo --invert-paths --path app.log --force
git remote add origin https://github.com/Bogzx/AutoFtmoCalendar.git
git push --force origin main
```

Note: `git filter-repo` removes the `origin` remote as a safety measure — re-add it as shown. After pushing, the user should also revoke the app's access at https://myaccount.google.com/permissions and re-authorize later (the old token may predate the leak).

---

### Task 2: Packaging scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/ftmo_calendar/__init__.py`
- Create: `src/ftmo_calendar/py.typed`
- Create: `tests/test_package.py`
- Delete: `requirements.txt` (superseded by pyproject)

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ftmo-calendar"
version = "0.2.0"
description = "Sync FTMO trading updates (maintenance windows, market closures) to Google Calendar"
readme = "README.md"
requires-python = ">=3.11"
license = { file = "LICENSE" }
authors = [{ name = "Bogdan-Alexandru Truta" }]
keywords = ["ftmo", "trading", "google-calendar", "maintenance"]
dependencies = [
  "requests>=2.31",
  "beautifulsoup4>=4.12",
  "pydantic>=2.5",
  "python-dotenv>=1.0",
  "google-api-python-client>=2.100",
  "google-auth>=2.23",
  "google-auth-oauthlib>=1.1",
  "google-genai>=1.0",
  "openai>=1.40",
  "tzdata>=2024.1",
]

[project.urls]
Repository = "https://github.com/Bogzx/AutoFtmoCalendar"

[project.scripts]
ftmo-calendar = "ftmo_calendar.cli:entry"

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.5", "mypy>=1.10", "types-requests"]

[tool.hatch.build.targets.wheel]
packages = ["src/ftmo_calendar"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
check_untyped_defs = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Note: `tzdata` is required because Windows has no system IANA timezone database for `zoneinfo`. `README.md` (lowercase) is created in Task 14 — until then `pip install -e .` warns about the readme; that's fine for editable installs.

- [ ] **Step 2: Create the package skeleton**

`src/ftmo_calendar/__init__.py`:

```python
"""Sync FTMO trading updates to Google Calendar."""

__version__ = "0.2.0"
```

`src/ftmo_calendar/py.typed`: empty file.

`tests/test_package.py`:

```python
from ftmo_calendar import __version__


def test_version() -> None:
    assert __version__
```

- [ ] **Step 3: Install and verify**

```powershell
pip install -e .[dev]
pytest -v
```

Expected: 1 passed.

- [ ] **Step 4: Remove requirements.txt and commit**

```powershell
git rm requirements.txt
git add -A; git commit -m "feat: src-layout packaging with pyproject.toml"
```

---

### Task 3: Core data model (`models.py`)

**Files:**
- Create: `src/ftmo_calendar/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`:

```python
from datetime import datetime, timezone

from ftmo_calendar.models import EventType, SourcePost, TradingEvent


def make_event(**overrides) -> TradingEvent:
    defaults = dict(
        event_type=EventType.MAINTENANCE,
        summary="Maintenance",
        description="desc",
        start=datetime(2026, 6, 6, 8, 0, tzinfo=timezone.utc),
        end=datetime(2026, 6, 6, 14, 0, tzinfo=timezone.utc),
        source_post_key="trading-update-2026-06-04",
        source_url="https://example.com/post",
    )
    defaults.update(overrides)
    return TradingEvent(**defaults)


def test_event_key_is_deterministic() -> None:
    assert make_event().event_key == make_event().event_key


def test_event_key_changes_with_times() -> None:
    other = make_event(end=datetime(2026, 6, 6, 22, 0, tzinfo=timezone.utc))
    assert make_event().event_key != other.event_key


def test_event_key_changes_with_post() -> None:
    other = make_event(source_post_key="trading-update-2026-06-11")
    assert make_event().event_key != other.event_key


def test_content_hash_is_stable() -> None:
    a = SourcePost(post_key="k", title="t", text="same text", url="u")
    b = SourcePost(post_key="k", title="t", text="same text", url="u")
    assert a.content_hash == b.content_hash
    c = SourcePost(post_key="k", title="t", text="different", url="u")
    assert a.content_hash != c.content_hash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/models.py`**

```python
"""Core data types shared across the pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    MAINTENANCE = "maintenance"
    CRYPTO_CLOSURE = "crypto_closure"
    HOLIDAY_HOURS = "holiday_hours"
    OTHER = "other"


@dataclass(frozen=True)
class SourcePost:
    """One announcement post extracted from a source."""

    post_key: str
    title: str
    text: str
    url: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TradingEvent:
    """A normalized, calendar-ready event."""

    event_type: EventType
    summary: str
    description: str
    start: datetime  # timezone-aware
    end: datetime  # timezone-aware
    source_post_key: str
    source_url: str

    @property
    def event_key(self) -> str:
        """Stable identity used for dedup and reconcile, stored on the Google event."""
        raw = "|".join(
            (
                self.source_post_key,
                self.event_type.value,
                self.start.isoformat(),
                self.end.isoformat(),
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v` — Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/models.py tests/test_models.py
git commit -m "feat: core data model with deterministic event keys"
```

---

### Task 4: Configuration (`config.py`)

**Files:**
- Create: `src/ftmo_calendar/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from ftmo_calendar.config import ConfigError, load_config


def test_defaults_without_config_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml", env={})
    assert cfg.source.url == "https://ftmo.com/en/trading-updates/"
    assert cfg.llm.provider == "gemini"
    assert cfg.calendar.auth_mode == "oauth"
    assert cfg.calendar.reminders_minutes == (60, 10)
    assert cfg.base_dir == tmp_path
    assert cfg.state_path == tmp_path / "state.json"


def test_toml_overrides(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        """
[llm]
provider = "openai-compatible"
base_url = "https://openrouter.ai/api/v1"
models = ["google/gemini-2.5-flash"]

[calendar]
auth_mode = "service_account"
calendar_id = "abc@group.calendar.google.com"
reminders_minutes = [30]

[events.summaries]
maintenance = "Platform down"
""",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "config.toml", env={})
    assert cfg.llm.provider == "openai-compatible"
    assert cfg.llm.models == ("google/gemini-2.5-flash",)
    assert cfg.calendar.calendar_id == "abc@group.calendar.google.com"
    assert cfg.calendar.reminders_minutes == (30,)
    assert cfg.events.summaries["maintenance"] == "Platform down"
    assert cfg.events.summaries["other"]  # defaults still merged


def test_api_key_from_env(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "config.toml", env={"LLM_API_KEY": "k1"})
    assert cfg.llm.api_key == "k1"
    legacy = load_config(tmp_path / "config.toml", env={"GEMINI_API_KEY": "k2"})
    assert legacy.llm.api_key == "k2"


def test_service_account_requires_calendar_id(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '[calendar]\nauth_mode = "service_account"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="calendar_id"):
        load_config(tmp_path / "config.toml", env={})


def test_invalid_provider_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[llm]\nprovider = "magic"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="provider"):
        load_config(tmp_path / "config.toml", env={})


def test_invalid_timezone_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[source]\ntimezone = "Mars/Olympus"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="timezone"):
        load_config(tmp_path / "config.toml", env={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/config.py`**

```python
"""Configuration loading: config.toml with environment-variable overrides for secrets."""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """Invalid or missing configuration."""


DEFAULT_SUMMARIES: dict[str, str] = {
    "maintenance": "⚠️ FTMO Platform Maintenance",
    "crypto_closure": "🚫 Crypto Market Closed",
    "holiday_hours": "🕒 Modified Trading Hours",
    "other": "ℹ️ FTMO Trading Update",
}


@dataclass(frozen=True)
class SourceConfig:
    url: str = "https://ftmo.com/en/trading-updates/"
    keywords: tuple[str, ...] = ("maintenance", "market is closed", "ctrader", "holiday", "crypto")
    timezone: str = "Europe/Bucharest"
    max_posts: int = 4
    max_age_days: int = 14


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "gemini"  # "gemini" | "openai-compatible"
    base_url: str = ""  # e.g. https://openrouter.ai/api/v1
    models: tuple[str, ...] = ("gemini-2.5-flash", "gemini-2.0-flash")
    api_key: str = ""  # from LLM_API_KEY / GEMINI_API_KEY env, never from TOML


@dataclass(frozen=True)
class CalendarConfig:
    auth_mode: str = "oauth"  # "oauth" | "service_account"
    name: str = "Trading"
    calendar_id: str = ""  # required for service_account; optional override for oauth
    timezone: str = "Europe/Bucharest"
    reminders_minutes: tuple[int, ...] = (60, 10)
    credentials_file: str = "credentials.json"
    token_file: str = "token.json"
    service_account_file: str = "service_account.json"


@dataclass(frozen=True)
class EventRules:
    max_duration_hours: int = 48
    max_days_ahead: int = 120
    summaries: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SUMMARIES))


@dataclass(frozen=True)
class AppConfig:
    source: SourceConfig
    llm: LLMConfig
    calendar: CalendarConfig
    events: EventRules
    base_dir: Path

    @property
    def state_path(self) -> Path:
        return self.base_dir / "state.json"

    def resolve(self, filename: str) -> Path:
        """Resolve a configured filename relative to the config directory."""
        p = Path(filename)
        return p if p.is_absolute() else self.base_dir / p


def _section(cls: type, data: dict, name: str):  # noqa: ANN001 - generic dataclass factory
    raw = data.get(name, {})
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in raw:
            value = raw[f.name]
            if isinstance(value, list):
                value = tuple(value)
            kwargs[f.name] = value
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise ConfigError(f"invalid [{name}] section: {e}") from e


def _validate(cfg: AppConfig) -> None:
    if cfg.llm.provider not in ("gemini", "openai-compatible"):
        raise ConfigError(
            f"unknown llm provider {cfg.llm.provider!r}; use 'gemini' or 'openai-compatible'"
        )
    if cfg.calendar.auth_mode not in ("oauth", "service_account"):
        raise ConfigError(
            f"unknown auth_mode {cfg.calendar.auth_mode!r}; use 'oauth' or 'service_account'"
        )
    if cfg.calendar.auth_mode == "service_account" and not cfg.calendar.calendar_id:
        raise ConfigError(
            "calendar.calendar_id is required with auth_mode='service_account' — create the "
            "calendar in Google Calendar, share it with the service account email, and put its "
            "ID here"
        )
    if not cfg.llm.models:
        raise ConfigError("llm.models must list at least one model")
    for tz_name in (cfg.source.timezone, cfg.calendar.timezone):
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ConfigError(f"invalid timezone {tz_name!r}: {e}") from e


def load_config(path: Path, env: Mapping[str, str] | None = None) -> AppConfig:
    """Load config from a TOML file (all keys optional) plus env-var secrets.

    A missing file is fine — every setting has a default. The config file's
    directory becomes the base for relative paths (token, state, …).
    """
    import os

    env_map = dict(os.environ if env is None else env)
    data: dict = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"cannot parse {path}: {e}") from e

    source = _section(SourceConfig, data, "source")
    llm = _section(LLMConfig, data, "llm")
    calendar = _section(CalendarConfig, data, "calendar")

    events_raw = data.get("events", {})
    if not isinstance(events_raw, dict):
        raise ConfigError("[events] must be a TOML table")
    summaries = {**DEFAULT_SUMMARIES, **events_raw.get("summaries", {})}
    events = EventRules(
        max_duration_hours=events_raw.get("max_duration_hours", EventRules.max_duration_hours),
        max_days_ahead=events_raw.get("max_days_ahead", EventRules.max_days_ahead),
        summaries=summaries,
    )

    api_key = env_map.get("LLM_API_KEY", "") or env_map.get("GEMINI_API_KEY", "")
    llm = dataclasses.replace(llm, api_key=api_key)

    cfg = AppConfig(
        source=source,
        llm=llm,
        calendar=calendar,
        events=events,
        base_dir=path.resolve().parent,
    )
    _validate(cfg)
    return cfg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v` — Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/config.py tests/test_config.py
git commit -m "feat: TOML config with env-var secrets and validation"
```

---

### Task 5: FTMO scraper (`sources/ftmo.py`)

**Files:**
- Create: `src/ftmo_calendar/sources/__init__.py` (empty)
- Create: `src/ftmo_calendar/sources/ftmo.py`
- Create: `tests/fixtures/listing.html`
- Create: `tests/fixtures/post.html`
- Test: `tests/test_ftmo_source.py`

- [ ] **Step 1: Create fixtures mirroring the verified live structure**

`tests/fixtures/listing.html`:

```html
<html><body>
<main>
  <span class="text-content-secondary font-medium">Published 6 days ago</span>
  <h1 class="h2 pt-2">Trading Update | Jun 4 2026</h1>
  <div class="content js-definition-point-for-toc-section tu">
    <h2 class="wp-block-heading" id="h-weekend-maintenance"><strong>Weekend Maintenance</strong></h2>
    <p>We will perform scheduled maintenance on <strong>Saturday, 6 Jun 2026</strong>.
    All trading platforms (MT5, MT4, and cTrader) will be under maintenance from 08:00 to 14:00.
    cTrader maintenance will continue from 14:00 to 22:00. All times are in GMT+3.</p>
  </div>
  <article class="post-card relative w-full rounded-2xl">
    <a href="https://ftmo.com/en/blog/trading-updates/trading-update-28-may-2026/"
       aria-label="Trading Update | 28 May 2026"></a>
    <span>Trading Update | 28 May 2026</span>
  </article>
  <article class="post-card relative w-full rounded-2xl">
    <a href="https://ftmo.com/en/blog/trading-updates/trading-update-21-may-2026/"
       aria-label="Trading Update | 21 May 2026"></a>
    <span>Trading Update | 21 May 2026</span>
  </article>
</main>
</body></html>
```

`tests/fixtures/post.html`:

```html
<html><body>
<main>
  <h1 class="h2">Trading Update | 28 May 2026</h1>
  <div class="content js-definition-point-for-toc-section tu">
    <h2 class="wp-block-heading"><strong>Crypto Maintenance</strong></h2>
    <p>The crypto market is closed on Saturday, 30 May 2026 from 10:00 to 12:00 GMT+3.</p>
  </div>
</main>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_ftmo_source.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_ftmo_source.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 4: Implement `src/ftmo_calendar/sources/ftmo.py`**

```python
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
                if response.status_code in (429,) or response.status_code >= 500:
                    raise FetchError(f"HTTP {response.status_code} from {url}")
                response.raise_for_status()
                return response.text
            except (requests.RequestException, FetchError) as e:
                last = e
                logger.warning("Fetch attempt %d/%d failed for %s: %s", attempt, self.retries, url, e)
                if attempt < self.retries:
                    time.sleep(2**attempt)
        raise FetchError(f"could not fetch {url} after {self.retries} attempts: {last}")
```

Create empty `src/ftmo_calendar/sources/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ftmo_source.py -v` — Expected: 8 passed.

- [ ] **Step 6: Commit**

```powershell
git add src/ftmo_calendar/sources tests/fixtures tests/test_ftmo_source.py
git commit -m "feat: multi-post FTMO scraper matching the redesigned site"
```

---

### Task 6: LLM extraction core (`parsing/llm.py`)

**Files:**
- Create: `src/ftmo_calendar/parsing/__init__.py` (empty)
- Create: `src/ftmo_calendar/parsing/llm.py`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_extractor.py`:

```python
import pytest

from ftmo_calendar.parsing.llm import (
    BackendError,
    EventExtractor,
    ExtractionError,
    RawEvent,
)

VALID_JSON = (
    '[{"event_type": "maintenance", "start_time": "2026-06-06T08:00:00",'
    ' "end_time": "2026-06-06T14:00:00", "stated_utc_offset": "+03:00",'
    ' "confidence": "high"}]'
)


class ScriptedBackend:
    """Returns queued responses; raises queued exceptions."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, model: str) -> str:
        self.calls.append((prompt, model))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_extracts_valid_events() -> None:
    backend = ScriptedBackend([VALID_JSON])
    events = EventExtractor(backend, ["m1"]).extract("some announcement")
    assert events == [
        RawEvent(
            event_type="maintenance",
            start_time="2026-06-06T08:00:00",
            end_time="2026-06-06T14:00:00",
            stated_utc_offset="+03:00",
            confidence="high",
        )
    ]


def test_strips_markdown_fences() -> None:
    backend = ScriptedBackend(["```json\n" + VALID_JSON + "\n```"])
    events = EventExtractor(backend, ["m1"]).extract("text")
    assert len(events) == 1


def test_repair_retry_on_invalid_json() -> None:
    backend = ScriptedBackend(["not json at all", VALID_JSON])
    events = EventExtractor(backend, ["m1"]).extract("text")
    assert len(events) == 1
    assert len(backend.calls) == 2
    assert "invalid" in backend.calls[1][0].lower()  # repair prompt mentions the failure


def test_falls_back_to_next_model() -> None:
    backend = ScriptedBackend([BackendError("quota"), VALID_JSON])
    events = EventExtractor(backend, ["m1", "m2"]).extract("text")
    assert len(events) == 1
    assert backend.calls[1][1] == "m2"


def test_raises_when_all_models_fail() -> None:
    backend = ScriptedBackend([BackendError("a"), BackendError("b")])
    with pytest.raises(ExtractionError):
        EventExtractor(backend, ["m1", "m2"]).extract("text")


def test_empty_array_is_valid() -> None:
    backend = ScriptedBackend(["[]"])
    assert EventExtractor(backend, ["m1"]).extract("text") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extractor.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/parsing/llm.py`**

```python
"""Provider-agnostic LLM extraction with validation, repair retry, and model fallback."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)


class RawEvent(BaseModel):
    """One event as extracted by the model, before validation/normalization."""

    event_type: Literal["maintenance", "crypto_closure", "holiday_hours", "other"]
    start_time: str
    end_time: str
    stated_utc_offset: str | None = None
    confidence: Literal["high", "low"] = "high"


_EVENTS = TypeAdapter(list[RawEvent])


class BackendError(Exception):
    """The LLM API call itself failed (quota, network, refusal)."""


class ExtractionError(Exception):
    """No model produced a valid extraction."""


class LLMBackend(Protocol):
    def complete(self, prompt: str, model: str) -> str: ...


PROMPT_TEMPLATE = """You extract scheduled trading interruptions from a prop-firm announcement.

Identify every scheduled platform maintenance window, crypto market closure, and \
modified/closed trading-hours period in the text below.

Rules:
- Output ONLY a JSON array, no prose and no markdown fences.
- Each element: {{"event_type": "maintenance"|"crypto_closure"|"holiday_hours"|"other", \
"start_time": "YYYY-MM-DDTHH:MM:SS", "end_time": "YYYY-MM-DDTHH:MM:SS", \
"stated_utc_offset": "+03:00" or null, "confidence": "high"|"low"}}
- If the text states a timezone (e.g. "GMT+3"), set stated_utc_offset to it ("+03:00"); else null.
- If an end time is implied rather than stated (e.g. "closed whole day"), infer it \
(00:00:00 to 23:59:00 of that day) and set confidence to "low".
- Ignore anything without a concrete scheduled date (general reminders, swap notices).
- If there are no scheduled events, output [].

Announcement text:
---
{text}
---
"""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class EventExtractor:
    def __init__(self, backend: LLMBackend, models: Sequence[str]) -> None:
        if not models:
            raise ValueError("at least one model is required")
        self.backend = backend
        self.models = list(models)

    def extract(self, text: str) -> list[RawEvent]:
        prompt = PROMPT_TEMPLATE.format(text=text)
        last_error: Exception | None = None
        for model in self.models:
            try:
                return self._extract_once(prompt, model)
            except (BackendError, ExtractionError) as e:
                logger.warning("Model %s failed: %s", model, e)
                last_error = e
        raise ExtractionError(f"all models failed; last error: {last_error}")

    def _extract_once(self, prompt: str, model: str) -> list[RawEvent]:
        raw = self.backend.complete(prompt, model)
        try:
            return self._parse(raw)
        except ValidationError as first:
            logger.info("Invalid extraction from %s; attempting repair retry", model)
            repair_prompt = (
                f"{prompt}\n\nYour previous reply was invalid: {str(first)[:500]}\n"
                "Reply again with ONLY the corrected JSON array."
            )
            raw = self.backend.complete(repair_prompt, model)
            try:
                return self._parse(raw)
            except ValidationError as second:
                raise ExtractionError(f"invalid JSON after repair retry: {second}") from second

    @staticmethod
    def _parse(raw: str) -> list[RawEvent]:
        cleaned = _FENCE.sub("", raw.strip()).strip()
        return _EVENTS.validate_json(cleaned)
```

Note: pydantic's `validate_json` raises `ValidationError` for malformed JSON as well as schema mismatches, so one except clause covers both.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extractor.py -v` — Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/parsing tests/test_extractor.py
git commit -m "feat: schema-validated LLM extraction with repair retry and model fallback"
```

---

### Task 7: LLM backends (`parsing/openai_compat.py`, `parsing/gemini.py`, factory)

**Files:**
- Create: `src/ftmo_calendar/parsing/openai_compat.py`
- Create: `src/ftmo_calendar/parsing/gemini.py`
- Create: `src/ftmo_calendar/parsing/factory.py`
- Test: `tests/test_backends.py`

- [ ] **Step 1: Write the failing tests** (factory logic only — the backends are thin SDK wrappers)

`tests/test_backends.py`:

```python
import pytest

from ftmo_calendar.config import ConfigError, LLMConfig
from ftmo_calendar.parsing.factory import make_backend


def test_missing_api_key_rejected() -> None:
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        make_backend(LLMConfig(api_key=""))


def test_gemini_backend_selected() -> None:
    backend = make_backend(LLMConfig(provider="gemini", api_key="k"))
    assert type(backend).__name__ == "GeminiBackend"


def test_openai_compatible_backend_selected() -> None:
    cfg = LLMConfig(provider="openai-compatible", api_key="k", base_url="https://openrouter.ai/api/v1")
    backend = make_backend(cfg)
    assert type(backend).__name__ == "OpenAICompatBackend"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backends.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement the two backends and the factory**

`src/ftmo_calendar/parsing/openai_compat.py`:

```python
"""Backend for any OpenAI-protocol endpoint: OpenRouter, OpenAI, Groq, Ollama, …"""

from __future__ import annotations

from openai import OpenAI, OpenAIError

from ftmo_calendar.parsing.llm import BackendError


class OpenAICompatBackend:
    def __init__(self, api_key: str, base_url: str = "") -> None:
        self._client = OpenAI(api_key=api_key, base_url=base_url or None)

    def complete(self, prompt: str, model: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        except OpenAIError as e:
            raise BackendError(str(e)) from e
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise BackendError(f"empty response from {model}")
        return content
```

`src/ftmo_calendar/parsing/gemini.py`:

```python
"""Backend for Google Gemini via the google-genai SDK."""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ftmo_calendar.parsing.llm import BackendError


class GeminiBackend:
    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def complete(self, prompt: str, model: str) -> str:
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
        except genai_errors.APIError as e:
            raise BackendError(str(e)) from e
        if not response.text:
            raise BackendError(f"empty response from {model}")
        return response.text
```

`src/ftmo_calendar/parsing/factory.py`:

```python
"""Construct the configured LLM backend (SDKs imported lazily)."""

from __future__ import annotations

from ftmo_calendar.config import ConfigError, LLMConfig
from ftmo_calendar.parsing.llm import LLMBackend


def make_backend(cfg: LLMConfig) -> LLMBackend:
    if not cfg.api_key:
        raise ConfigError(
            "no API key found — set the LLM_API_KEY environment variable "
            "(or GEMINI_API_KEY for backward compatibility), e.g. in a .env file"
        )
    if cfg.provider == "gemini":
        from ftmo_calendar.parsing.gemini import GeminiBackend

        return GeminiBackend(cfg.api_key)
    from ftmo_calendar.parsing.openai_compat import OpenAICompatBackend

    return OpenAICompatBackend(cfg.api_key, cfg.base_url)
```

(`load_config` already rejects unknown providers, so the factory only sees valid ones.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backends.py -v` — Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/parsing tests/test_backends.py
git commit -m "feat: gemini and openai-compatible LLM backends"
```

---

### Task 8: Validation & normalization (`parsing/validate.py`)

**Files:**
- Create: `src/ftmo_calendar/parsing/validate.py`
- Test: `tests/test_validate.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_validate.py`:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ftmo_calendar.config import EventRules
from ftmo_calendar.models import EventType, SourcePost
from ftmo_calendar.parsing.llm import RawEvent
from ftmo_calendar.parsing.validate import validate_events

TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
POST = SourcePost(
    post_key="trading-update-2026-06-04",
    title="Trading Update | Jun 4 2026",
    text="Maintenance on Saturday. " * 100,
    url="https://ftmo.com/en/trading-updates/",
)


def raw(start="2026-06-06T08:00:00", end="2026-06-06T14:00:00", **kw) -> RawEvent:
    defaults = dict(event_type="maintenance", start_time=start, end_time=end,
                    stated_utc_offset="+03:00", confidence="high")
    defaults.update(kw)
    return RawEvent(**defaults)


def run(events, rules=None):
    return validate_events(events, POST, rules or EventRules(), TZ, TZ, now=NOW)


def test_valid_event_converted() -> None:
    events, rejections = run([raw()])
    assert rejections == []
    [event] = events
    assert event.event_type is EventType.MAINTENANCE
    assert event.start.isoformat() == "2026-06-06T08:00:00+03:00"
    assert event.summary == EventRules().summaries["maintenance"]
    assert "https://ftmo.com/en/trading-updates/" in event.description
    assert len(event.description) < 1000  # excerpt is trimmed
    assert event.source_post_key == POST.post_key


def test_missing_offset_uses_source_timezone() -> None:
    events, _ = run([raw(stated_utc_offset=None)])
    assert events[0].start.utcoffset() == datetime(2026, 6, 6, tzinfo=TZ).utcoffset()


def test_end_before_start_rejected() -> None:
    events, rejections = run([raw(start="2026-06-06T14:00:00", end="2026-06-06T08:00:00")])
    assert events == [] and "after start" in rejections[0].reason


def test_overlong_duration_rejected() -> None:
    events, rejections = run([raw(end="2026-06-09T08:00:00")])
    assert events == [] and "duration" in rejections[0].reason


def test_too_far_ahead_rejected() -> None:
    events, rejections = run([raw(start="2027-06-06T08:00:00", end="2027-06-06T14:00:00")])
    assert events == [] and "future" in rejections[0].reason


def test_already_ended_rejected() -> None:
    events, rejections = run([raw(start="2026-05-01T08:00:00", end="2026-05-01T14:00:00")])
    assert events == [] and "ended" in rejections[0].reason


def test_unparseable_datetime_rejected() -> None:
    events, rejections = run([raw(start="whenever")])
    assert events == [] and "datetime" in rejections[0].reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_validate.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/parsing/validate.py`**

```python
"""Convert raw LLM extractions into validated, timezone-aware TradingEvents."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ftmo_calendar.config import EventRules
from ftmo_calendar.models import EventType, SourcePost, TradingEvent
from ftmo_calendar.parsing.llm import RawEvent

logger = logging.getLogger(__name__)

_OFFSET = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2}):?(\d{2})?$")
_EXCERPT_LIMIT = 800


@dataclass(frozen=True)
class Rejection:
    raw: RawEvent
    reason: str


def _offset_tz(stated: str) -> timezone | None:
    m = _OFFSET.match(stated.strip())
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours, minutes = int(m.group(2)), int(m.group(3) or 0)
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def build_description(post: SourcePost) -> str:
    excerpt = post.text[:_EXCERPT_LIMIT]
    if len(post.text) > _EXCERPT_LIMIT:
        excerpt += "…"
    return f"{excerpt}\n\nSource: {post.url}\nCreated by AutoFtmoCalendar"


def validate_events(
    raw_events: list[RawEvent],
    post: SourcePost,
    rules: EventRules,
    source_tz: ZoneInfo,
    calendar_tz: ZoneInfo,
    now: datetime | None = None,
) -> tuple[list[TradingEvent], list[Rejection]]:
    now = now or datetime.now(timezone.utc)
    events: list[TradingEvent] = []
    rejections: list[Rejection] = []

    for raw in raw_events:
        try:
            start = datetime.fromisoformat(raw.start_time)
            end = datetime.fromisoformat(raw.end_time)
        except ValueError as e:
            rejections.append(Rejection(raw, f"unparseable datetime: {e}"))
            continue

        stated = _offset_tz(raw.stated_utc_offset) if raw.stated_utc_offset else None
        if start.tzinfo is None:
            start = start.replace(tzinfo=stated or source_tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=stated or source_tz)

        if end <= start:
            rejections.append(Rejection(raw, "end is not after start"))
        elif end - start > timedelta(hours=rules.max_duration_hours):
            rejections.append(
                Rejection(raw, f"duration exceeds {rules.max_duration_hours}h sanity cap")
            )
        elif start > now + timedelta(days=rules.max_days_ahead):
            rejections.append(Rejection(raw, "too far in the future"))
        elif end <= now:
            rejections.append(Rejection(raw, "already ended"))
        else:
            event_type = EventType(raw.event_type)
            events.append(
                TradingEvent(
                    event_type=event_type,
                    summary=rules.summaries.get(event_type.value, rules.summaries["other"]),
                    description=build_description(post),
                    start=start.astimezone(calendar_tz),
                    end=end.astimezone(calendar_tz),
                    source_post_key=post.post_key,
                    source_url=post.url,
                )
            )
    return events, rejections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_validate.py -v` — Expected: 7 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/parsing/validate.py tests/test_validate.py
git commit -m "feat: sanity validation and timezone normalization for extracted events"
```

---

### Task 9: Run state (`state.py`)

**Files:**
- Create: `src/ftmo_calendar/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_state.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from ftmo_calendar.state import PostState, State, TrackedEvent, load_state, save_state

NOW = datetime(2026, 6, 9, tzinfo=timezone.utc)


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    state = load_state(tmp_path / "state.json")
    assert state.posts == {}


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = State(
        posts={
            "p1": PostState(
                content_hash="abc",
                last_seen="2026-06-09T00:00:00+00:00",
                events=[TrackedEvent("k1", "gid1", "2026-06-10T00:00:00+00:00")],
            )
        }
    )
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.posts["p1"].content_hash == "abc"
    assert loaded.posts["p1"].events[0].google_event_id == "gid1"


def test_prune_drops_stale_posts_with_ended_events(tmp_path: Path) -> None:
    state = State(
        posts={
            "stale": PostState(
                content_hash="a",
                last_seen="2026-01-01T00:00:00+00:00",
                events=[TrackedEvent("k", "g", "2026-01-02T00:00:00+00:00")],
            ),
            "stale-but-future-event": PostState(
                content_hash="b",
                last_seen="2026-01-01T00:00:00+00:00",
                events=[TrackedEvent("k2", "g2", "2026-07-01T00:00:00+00:00")],
            ),
            "fresh": PostState(content_hash="c", last_seen="2026-06-08T00:00:00+00:00"),
        }
    )
    state.prune(now=NOW)
    assert set(state.posts) == {"stale-but-future-event", "fresh"}


def test_corrupt_state_file_resets(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    state = load_state(path)
    assert state.posts == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/state.py`**

```python
"""Persistent run state: which posts were seen and which events were created."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_VERSION = 1
_PRUNE_AFTER_DAYS = 45


@dataclass
class TrackedEvent:
    event_key: str
    google_event_id: str
    end: str  # ISO 8601, timezone-aware


@dataclass
class PostState:
    content_hash: str
    last_seen: str  # ISO 8601, timezone-aware
    events: list[TrackedEvent] = field(default_factory=list)


@dataclass
class State:
    posts: dict[str, PostState] = field(default_factory=dict)

    def prune(self, now: datetime | None = None) -> None:
        """Drop posts not seen recently whose events have all ended."""
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=_PRUNE_AFTER_DAYS)
        for key in list(self.posts):
            post = self.posts[key]
            if datetime.fromisoformat(post.last_seen) >= cutoff:
                continue
            if all(datetime.fromisoformat(e.end) < now for e in post.events):
                del self.posts[key]


def load_state(path: Path) -> State:
    if not path.exists():
        return State()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        posts = {
            key: PostState(
                content_hash=p["content_hash"],
                last_seen=p["last_seen"],
                events=[TrackedEvent(**e) for e in p.get("events", [])],
            )
            for key, p in data.get("posts", {}).items()
        }
        return State(posts=posts)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("State file %s is corrupt (%s); starting fresh", path, e)
        return State()


def save_state(state: State, path: Path) -> None:
    payload = {"version": STATE_VERSION, "posts": {k: asdict(v) for k, v in state.posts.items()}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py -v` — Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/state.py tests/test_state.py
git commit -m "feat: persistent post/event state with pruning and atomic writes"
```

---

### Task 10: Google credentials (`sinks/auth.py`)

**Files:**
- Create: `src/ftmo_calendar/sinks/__init__.py` (empty)
- Create: `src/ftmo_calendar/sinks/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing tests** (error paths — the happy paths are thin wrappers over Google SDKs)

`tests/test_auth.py`:

```python
from pathlib import Path

import pytest

from ftmo_calendar.config import CalendarConfig
from ftmo_calendar.sinks.auth import AuthError, load_credentials


def test_oauth_without_token_gives_actionable_error(tmp_path: Path) -> None:
    cfg = CalendarConfig(auth_mode="oauth")
    with pytest.raises(AuthError, match="ftmo-calendar auth"):
        load_credentials(cfg, tmp_path)


def test_service_account_missing_key_file(tmp_path: Path) -> None:
    cfg = CalendarConfig(auth_mode="service_account", calendar_id="x@group.calendar.google.com")
    with pytest.raises(AuthError, match="service_account.json"):
        load_credentials(cfg, tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/sinks/auth.py`**

```python
"""Google Calendar credentials.

Two modes:
- service_account: key file + calendar shared with the service account. Never
  expires, no browser — the right choice for servers and cron.
- oauth: token.json produced by the explicit `ftmo-calendar auth` command.
  `run` NEVER starts an interactive flow (it would hang a headless cron run);
  it refreshes silently or fails with instructions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from ftmo_calendar.config import CalendarConfig

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_TESTING_MODE_TIP = (
    "Tip: OAuth apps left in 'Testing' publishing status get refresh tokens that expire "
    "every 7 days. In the Google Cloud console, publish your OAuth consent screen to "
    "'Production' to get long-lived tokens."
)


class AuthError(Exception):
    """Credentials missing or invalid; the message tells the user what to do."""


def _resolve(base_dir: Path, filename: str) -> Path:
    p = Path(filename)
    return p if p.is_absolute() else base_dir / p


def load_credentials(cfg: CalendarConfig, base_dir: Path):
    if cfg.auth_mode == "service_account":
        return _load_service_account(cfg, base_dir)
    return _load_oauth(cfg, base_dir)


def _load_service_account(cfg: CalendarConfig, base_dir: Path):
    from google.oauth2 import service_account

    key_path = _resolve(base_dir, cfg.service_account_file)
    if not key_path.exists():
        raise AuthError(
            f"Service account key not found: {key_path}\n"
            "Create a service account in the Google Cloud console, download its JSON key "
            f"to that path, and share your calendar with the service account's email "
            "(permission: 'Make changes to events')."
        )
    try:
        return service_account.Credentials.from_service_account_file(
            str(key_path), scopes=SCOPES
        )
    except (ValueError, GoogleAuthError) as e:
        raise AuthError(f"Invalid service account key {key_path}: {e}") from e


def _load_oauth(cfg: CalendarConfig, base_dir: Path):
    token_path = _resolve(base_dir, cfg.token_file)
    if not token_path.exists():
        raise AuthError(
            f"No OAuth token at {token_path}. Run `ftmo-calendar auth` once on a machine "
            "with a browser to authorize."
        )
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except ValueError as e:
        raise AuthError(f"OAuth token {token_path} is corrupt: {e}. Run `ftmo-calendar auth`.") from e
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise AuthError(
                "OAuth token refresh failed (expired or revoked). "
                f"Run `ftmo-calendar auth` to re-authorize.\n{_TESTING_MODE_TIP}"
            ) from e
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info("Refreshed OAuth token")
        return creds
    raise AuthError(
        f"OAuth token at {token_path} is not refreshable. Run `ftmo-calendar auth`.\n"
        f"{_TESTING_MODE_TIP}"
    )


def interactive_auth(cfg: CalendarConfig, base_dir: Path) -> Path:
    """Run the browser OAuth flow. Only called by the `auth` CLI command."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = _resolve(base_dir, cfg.credentials_file)
    if not creds_path.exists():
        raise AuthError(
            f"OAuth client file not found: {creds_path}\n"
            "Download credentials.json for a 'Desktop app' OAuth client from the "
            "Google Cloud console (APIs & Services → Credentials)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    token_path = _resolve(base_dir, cfg.token_file)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return token_path


def describe_credentials(cfg: CalendarConfig, base_dir: Path) -> str:
    """Human-readable status for `ftmo-calendar auth --check`."""
    if cfg.auth_mode == "service_account":
        key_path = _resolve(base_dir, cfg.service_account_file)
        if not key_path.exists():
            return f"service_account: key file MISSING at {key_path}"
        return f"service_account: key file present at {key_path} (no expiry)"
    token_path = _resolve(base_dir, cfg.token_file)
    if not token_path.exists():
        return f"oauth: NO token at {token_path} — run `ftmo-calendar auth`"
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except ValueError:
        return f"oauth: token at {token_path} is CORRUPT — run `ftmo-calendar auth`"
    expiry = creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry else None
    status = "valid" if creds.valid else "expired (will auto-refresh on next run)"
    refresh = "yes" if creds.refresh_token else "NO — re-run `ftmo-calendar auth`"
    now = datetime.now(timezone.utc)
    expiry_text = f"{expiry.isoformat()} ({'past' if expiry and expiry < now else 'future'})" if expiry else "unknown"
    return (
        f"oauth: token {status}\n"
        f"  access token expiry: {expiry_text}\n"
        f"  refresh token present: {refresh}\n"
        f"  {_TESTING_MODE_TIP}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v` — Expected: 2 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/sinks tests/test_auth.py
git commit -m "feat: hardened Google auth with service-account mode and explicit oauth command"
```

---

### Task 11: Google Calendar sink (`sinks/base.py`, `sinks/google_calendar.py`)

**Files:**
- Create: `src/ftmo_calendar/sinks/base.py`
- Create: `src/ftmo_calendar/sinks/google_calendar.py`
- Test: `tests/test_calendar_sink.py`

- [ ] **Step 1: Write the failing tests** (pure event-body builder — API calls are thin)

`tests/test_calendar_sink.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from ftmo_calendar.models import EventType, TradingEvent
from ftmo_calendar.sinks.google_calendar import PRIVATE_KEY_PROP, build_event_body

TZ = ZoneInfo("Europe/Bucharest")
EVENT = TradingEvent(
    event_type=EventType.MAINTENANCE,
    summary="⚠️ FTMO Platform Maintenance",
    description="details…",
    start=datetime(2026, 6, 6, 8, 0, tzinfo=TZ),
    end=datetime(2026, 6, 6, 14, 0, tzinfo=TZ),
    source_post_key="trading-update-2026-06-04",
    source_url="https://ftmo.com/en/trading-updates/",
)


def test_event_body_has_times_and_zone() -> None:
    body = build_event_body(EVENT, "Europe/Bucharest", (60, 10))
    assert body["start"] == {"dateTime": "2026-06-06T08:00:00+03:00", "timeZone": "Europe/Bucharest"}
    assert body["end"]["dateTime"] == "2026-06-06T14:00:00+03:00"


def test_event_body_sets_reminders() -> None:
    body = build_event_body(EVENT, "Europe/Bucharest", (60, 10))
    assert body["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 60}, {"method": "popup", "minutes": 10}],
    }


def test_event_body_carries_reconcile_key() -> None:
    body = build_event_body(EVENT, "Europe/Bucharest", ())
    assert body["extendedProperties"]["private"][PRIVATE_KEY_PROP] == EVENT.event_key
    assert body["reminders"] == {"useDefault": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calendar_sink.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement the protocol and sink**

`src/ftmo_calendar/sinks/base.py`:

```python
"""Sink protocol — what the pipeline needs from a calendar backend."""

from __future__ import annotations

from typing import Protocol

from ftmo_calendar.models import TradingEvent


class EventSink(Protocol):
    def find_event_id_by_key(self, event_key: str) -> str | None: ...

    def create_event(self, event: TradingEvent) -> str:
        """Create the event; returns the backend's event id."""
        ...

    def delete_event(self, event_id: str) -> None: ...
```

`src/ftmo_calendar/sinks/google_calendar.py`:

```python
"""Google Calendar sink with reconcile-key support."""

from __future__ import annotations

import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ftmo_calendar.config import CalendarConfig
from ftmo_calendar.models import TradingEvent

logger = logging.getLogger(__name__)

PRIVATE_KEY_PROP = "aftc_key"


class CalendarSinkError(Exception):
    """A Google Calendar API operation failed."""


def build_event_body(
    event: TradingEvent, timezone_name: str, reminders_minutes: tuple[int, ...]
) -> dict:
    reminders: dict = {"useDefault": True}
    if reminders_minutes:
        reminders = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in reminders_minutes],
        }
    return {
        "summary": event.summary,
        "description": event.description,
        "start": {"dateTime": event.start.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": event.end.isoformat(), "timeZone": timezone_name},
        "reminders": reminders,
        "extendedProperties": {"private": {PRIVATE_KEY_PROP: event.event_key}},
    }


class GoogleCalendarSink:
    def __init__(self, credentials, cfg: CalendarConfig) -> None:  # noqa: ANN001
        self._cfg = cfg
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self.calendar_id = self._resolve_calendar()

    def _resolve_calendar(self) -> str:
        if self._cfg.calendar_id:
            return self._cfg.calendar_id
        # oauth mode: find or create the named calendar
        try:
            page = self._service.calendarList().list().execute()
            for entry in page.get("items", []):
                if entry.get("summary") == self._cfg.name:
                    logger.info("Using existing calendar '%s'", self._cfg.name)
                    return entry["id"]
            created = (
                self._service.calendars()
                .insert(body={"summary": self._cfg.name, "timeZone": self._cfg.timezone})
                .execute()
            )
            logger.info("Created calendar '%s'", self._cfg.name)
            return created["id"]
        except HttpError as e:
            raise CalendarSinkError(f"calendar lookup/creation failed: {e}") from e

    def find_event_id_by_key(self, event_key: str) -> str | None:
        try:
            result = (
                self._service.events()
                .list(
                    calendarId=self.calendar_id,
                    privateExtendedProperty=f"{PRIVATE_KEY_PROP}={event_key}",
                    maxResults=1,
                    singleEvents=True,
                )
                .execute()
            )
        except HttpError as e:
            raise CalendarSinkError(f"event lookup failed: {e}") from e
        items = result.get("items", [])
        return items[0]["id"] if items else None

    def create_event(self, event: TradingEvent) -> str:
        body = build_event_body(event, self._cfg.timezone, self._cfg.reminders_minutes)
        try:
            created = (
                self._service.events().insert(calendarId=self.calendar_id, body=body).execute()
            )
        except HttpError as e:
            raise CalendarSinkError(f"event creation failed: {e}") from e
        logger.info("Created event: %s", created.get("htmlLink", created.get("id")))
        return created["id"]

    def delete_event(self, event_id: str) -> None:
        try:
            self._service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        except HttpError as e:
            if e.resp is not None and e.resp.status in (404, 410):
                logger.info("Event %s already gone", event_id)
                return
            raise CalendarSinkError(f"event deletion failed: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calendar_sink.py -v` — Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/sinks tests/test_calendar_sink.py
git commit -m "feat: Google Calendar sink with reconcile keys and reminders"
```

---

### Task 12: Pipeline (`pipeline.py`)

**Files:**
- Create: `src/ftmo_calendar/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from ftmo_calendar.config import AppConfig, CalendarConfig, EventRules, LLMConfig, SourceConfig
from ftmo_calendar.models import SourcePost, TradingEvent
from ftmo_calendar.parsing.llm import RawEvent
from ftmo_calendar.pipeline import run_pipeline
from ftmo_calendar.state import PostState, State, TrackedEvent

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

POST = SourcePost(
    post_key="trading-update-2026-06-04",
    title="Trading Update | Jun 4 2026",
    text="ctrader maintenance on Saturday 6 Jun 2026 08:00 to 14:00 GMT+3",
    url="https://ftmo.com/en/trading-updates/",
)

RAW = RawEvent(
    event_type="maintenance",
    start_time="2026-06-06T08:00:00",
    end_time="2026-06-06T14:00:00",
    stated_utc_offset="+03:00",
)


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        source=SourceConfig(),
        llm=LLMConfig(api_key="test"),
        calendar=CalendarConfig(),
        events=EventRules(),
        base_dir=tmp_path,
    )


class FakeSource:
    def __init__(self, posts: list[SourcePost]) -> None:
        self.posts = posts

    def fetch(self) -> list[SourcePost]:
        return self.posts


class FakeExtractor:
    def __init__(self, result: list[RawEvent]) -> None:
        self.result = result
        self.calls = 0

    def extract(self, text: str) -> list[RawEvent]:
        self.calls += 1
        return self.result


class FakeSink:
    def __init__(self) -> None:
        self.created: list[TradingEvent] = []
        self.deleted: list[str] = []
        self.existing_by_key: dict[str, str] = {}
        self._next_id = 0

    def find_event_id_by_key(self, event_key: str) -> str | None:
        return self.existing_by_key.get(event_key)

    def create_event(self, event: TradingEvent) -> str:
        self.created.append(event)
        self._next_id += 1
        return f"gid{self._next_id}"

    def delete_event(self, event_id: str) -> None:
        self.deleted.append(event_id)


def test_new_post_creates_events_and_updates_state(tmp_path: Path) -> None:
    sink, state = FakeSink(), State()
    report = run_pipeline(
        source=FakeSource([POST]),
        extractor=FakeExtractor([RAW]),
        sink=sink,
        state=state,
        config=make_config(tmp_path),
        now=NOW,
    )
    assert report.events_created == 1
    assert len(sink.created) == 1
    tracked = state.posts[POST.post_key]
    assert tracked.content_hash == POST.content_hash
    assert tracked.events[0].google_event_id == "gid1"


def test_unchanged_post_skips_llm(tmp_path: Path) -> None:
    extractor = FakeExtractor([RAW])
    state = State(
        posts={
            POST.post_key: PostState(
                content_hash=POST.content_hash,
                last_seen="2026-05-31T00:00:00+00:00",
                events=[TrackedEvent("k", "g", "2026-06-06T14:00:00+03:00")],
            )
        }
    )
    report = run_pipeline(
        source=FakeSource([POST]),
        extractor=extractor,
        sink=FakeSink(),
        state=state,
        config=make_config(tmp_path),
        now=NOW,
    )
    assert extractor.calls == 0
    assert report.posts_skipped_unchanged == 1
    assert state.posts[POST.post_key].last_seen == NOW.isoformat()


def test_changed_post_reconciles(tmp_path: Path) -> None:
    """A rescheduled announcement deletes the future stale event and creates the new one."""
    sink = FakeSink()
    state = State(
        posts={
            POST.post_key: PostState(
                content_hash="old-hash",
                last_seen="2026-05-31T00:00:00+00:00",
                events=[TrackedEvent("stale-key", "stale-gid", "2026-06-07T14:00:00+03:00")],
            )
        }
    )
    report = run_pipeline(
        source=FakeSource([POST]),
        extractor=FakeExtractor([RAW]),
        sink=sink,
        state=state,
        config=make_config(tmp_path),
        now=NOW,
    )
    assert sink.deleted == ["stale-gid"]
    assert report.events_created == 1 and report.events_deleted == 1
    keys = [e.event_key for e in state.posts[POST.post_key].events]
    assert "stale-key" not in keys


def test_ended_events_are_never_deleted(tmp_path: Path) -> None:
    sink = FakeSink()
    state = State(
        posts={
            POST.post_key: PostState(
                content_hash="old-hash",
                last_seen="2026-05-31T00:00:00+00:00",
                events=[TrackedEvent("past-key", "past-gid", "2026-05-30T14:00:00+03:00")],
            )
        }
    )
    run_pipeline(
        source=FakeSource([POST]),
        extractor=FakeExtractor([RAW]),
        sink=sink,
        state=state,
        config=make_config(tmp_path),
        now=NOW,
    )
    assert sink.deleted == []
    keys = [e.event_key for e in state.posts[POST.post_key].events]
    assert "past-key" in keys  # history preserved


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    sink, state = FakeSink(), State()
    report = run_pipeline(
        source=FakeSource([POST]),
        extractor=FakeExtractor([RAW]),
        sink=sink,
        state=state,
        config=make_config(tmp_path),
        dry_run=True,
        now=NOW,
    )
    assert report.events_created == 1  # reported…
    assert sink.created == [] and state.posts == {}  # …but nothing performed


def test_irrelevant_post_skipped(tmp_path: Path) -> None:
    boring = SourcePost(post_key="p", title="t", text="nothing interesting here", url="u")
    extractor = FakeExtractor([RAW])
    report = run_pipeline(
        source=FakeSource([boring]),
        extractor=extractor,
        sink=FakeSink(),
        state=State(),
        config=make_config(tmp_path),
        now=NOW,
    )
    assert extractor.calls == 0
    assert report.posts_relevant == 0


def test_calendar_recovery_via_key_lookup(tmp_path: Path) -> None:
    """State lost but the event already exists in the calendar -> reuse, don't duplicate."""
    sink = FakeSink()
    config = make_config(tmp_path)
    # Compute the real event key by running once, then simulate state loss.
    state = State()
    run_pipeline(
        source=FakeSource([POST]), extractor=FakeExtractor([RAW]), sink=sink,
        state=state, config=config, now=NOW,
    )
    key = state.posts[POST.post_key].events[0].event_key
    sink2 = FakeSink()
    sink2.existing_by_key[key] = "preexisting-gid"
    fresh_state = State()
    report = run_pipeline(
        source=FakeSource([POST]), extractor=FakeExtractor([RAW]), sink=sink2,
        state=fresh_state, config=config, now=NOW,
    )
    assert sink2.created == []
    assert report.events_kept == 1
    assert fresh_state.posts[POST.post_key].events[0].google_event_id == "preexisting-gid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v` — Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `src/ftmo_calendar/pipeline.py`**

```python
"""Orchestration: fetch → cache-check → extract → validate → reconcile."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from ftmo_calendar.config import AppConfig
from ftmo_calendar.models import SourcePost, TradingEvent
from ftmo_calendar.parsing.llm import RawEvent
from ftmo_calendar.parsing.validate import validate_events
from ftmo_calendar.sinks.base import EventSink
from ftmo_calendar.state import PostState, State, TrackedEvent

logger = logging.getLogger(__name__)


class Source(Protocol):
    def fetch(self) -> list[SourcePost]: ...


class Extractor(Protocol):
    def extract(self, text: str) -> list[RawEvent]: ...


@dataclass
class RunReport:
    posts_seen: int = 0
    posts_relevant: int = 0
    posts_skipped_unchanged: int = 0
    events_created: int = 0
    events_deleted: int = 0
    events_kept: int = 0
    rejections: int = 0
    dry_run: bool = False

    def summary(self) -> str:
        prefix = "[dry-run] " if self.dry_run else ""
        return (
            f"{prefix}posts: {self.posts_seen} seen, {self.posts_relevant} relevant, "
            f"{self.posts_skipped_unchanged} unchanged | events: {self.events_created} created, "
            f"{self.events_deleted} removed, {self.events_kept} kept, "
            f"{self.rejections} rejected extractions"
        )


def run_pipeline(
    *,
    source: Source,
    extractor: Extractor,
    sink: EventSink,
    state: State,
    config: AppConfig,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RunReport:
    now = now or datetime.now(timezone.utc)
    report = RunReport(dry_run=dry_run)
    source_tz = ZoneInfo(config.source.timezone)
    calendar_tz = ZoneInfo(config.calendar.timezone)

    posts = source.fetch()
    report.posts_seen = len(posts)

    for post in posts:
        post_state = state.posts.get(post.post_key)
        if post_state is not None and not dry_run:
            post_state.last_seen = now.isoformat()

        if not _is_relevant(post, config.source.keywords):
            logger.info("Post %s has no relevant keywords; skipping", post.post_key)
            continue
        report.posts_relevant += 1

        if post_state is not None and post_state.content_hash == post.content_hash:
            logger.info("Post %s unchanged; skipping LLM call", post.post_key)
            report.posts_skipped_unchanged += 1
            continue

        logger.info("Post %s is new or changed; extracting events", post.post_key)
        raw_events = extractor.extract(post.text)
        events, rejections = validate_events(
            raw_events, post, config.events, source_tz, calendar_tz, now=now
        )
        report.rejections += len(rejections)
        for rejection in rejections:
            logger.warning("Rejected extraction for %s: %s", post.post_key, rejection.reason)

        new_post_state = _reconcile(post, events, post_state, sink, report, dry_run, now)
        if not dry_run:
            state.posts[post.post_key] = new_post_state

    if not dry_run:
        state.prune(now=now)
    return report


def _is_relevant(post: SourcePost, keywords: tuple[str, ...]) -> bool:
    text = post.text.lower()
    return any(k.strip().lower() in text for k in keywords if k.strip())


def _reconcile(
    post: SourcePost,
    events: list[TradingEvent],
    post_state: PostState | None,
    sink: EventSink,
    report: RunReport,
    dry_run: bool,
    now: datetime,
) -> PostState:
    old = {e.event_key: e for e in (post_state.events if post_state else [])}
    new_keys = {e.event_key for e in events}
    tracked: list[TrackedEvent] = []

    for key, old_event in old.items():
        if key in new_keys:
            continue
        if datetime.fromisoformat(old_event.end) <= now:
            tracked.append(old_event)  # it happened; preserve calendar history
            continue
        logger.info("Announcement changed: removing stale event %s", key)
        if not dry_run:
            sink.delete_event(old_event.google_event_id)
        report.events_deleted += 1

    for event in events:
        if event.event_key in old:
            tracked.append(old[event.event_key])
            report.events_kept += 1
            continue
        if dry_run:
            logger.info("[dry-run] would create '%s' at %s", event.summary, event.start)
            report.events_created += 1
            continue
        existing_id = sink.find_event_id_by_key(event.event_key)
        if existing_id:
            logger.info("Event %s already in calendar; adopting it", event.event_key)
            tracked.append(TrackedEvent(event.event_key, existing_id, event.end.isoformat()))
            report.events_kept += 1
            continue
        google_id = sink.create_event(event)
        tracked.append(TrackedEvent(event.event_key, google_id, event.end.isoformat()))
        report.events_created += 1

    return PostState(
        content_hash=post.content_hash, last_seen=now.isoformat(), events=tracked
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v` — Expected: 7 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/ftmo_calendar/pipeline.py tests/test_pipeline.py
git commit -m "feat: reconcile pipeline with caching, dry-run, and history preservation"
```

---

### Task 13: CLI (`cli.py`)

**Files:**
- Create: `src/ftmo_calendar/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from pathlib import Path

import pytest

import ftmo_calendar.cli as cli
from ftmo_calendar.pipeline import RunReport


def test_run_is_default_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}

    def fake_run(config, dry_run):
        calls["dry_run"] = dry_run
        return cli.EXIT_OK

    monkeypatch.setattr(cli, "_cmd_run", fake_run)
    assert cli.main(["--config", str(tmp_path / "config.toml")]) == cli.EXIT_OK
    assert calls["dry_run"] is False


def test_dry_run_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {}
    monkeypatch.setattr(
        cli, "_cmd_run", lambda config, dry_run: calls.update(dry_run=dry_run) or cli.EXIT_OK
    )
    cli.main(["--config", str(tmp_path / "config.toml"), "run", "--dry-run"])
    assert calls["dry_run"] is True


def test_config_error_exits_2(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[llm]\nprovider = "bogus"\n', encoding="utf-8")
    assert cli.main(["--config", str(tmp_path / "config.toml")]) == cli.EXIT_CONFIG


def test_pipeline_failure_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(config, dry_run):
        raise RuntimeError("scraper exploded")

    monkeypatch.setattr(cli, "_cmd_run", boom)
    assert cli.main(["--config", str(tmp_path / "config.toml")]) == cli.EXIT_ERROR


def test_status_with_no_state(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["--config", str(tmp_path / "config.toml"), "status"]) == cli.EXIT_OK
    assert "no runs recorded" in capsys.readouterr().out.lower()


def test_report_summary_format() -> None:
    report = RunReport(posts_seen=3, posts_relevant=2, events_created=1, dry_run=True)
    text = report.summary()
    assert "[dry-run]" in text and "1 created" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v` — Expected: FAIL (ModuleNotFoundError on cli import).

- [ ] **Step 3: Implement `src/ftmo_calendar/cli.py`**

```python
"""Command-line interface: ftmo-calendar run|auth|status."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from ftmo_calendar import __version__
from ftmo_calendar.config import AppConfig, ConfigError, load_config

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ftmo-calendar",
        description="Sync FTMO trading updates (maintenance, closures) to Google Calendar.",
    )
    parser.add_argument("--config", type=Path, default=Path("config.toml"),
                        help="path to config.toml (default: ./config.toml)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="check FTMO and sync the calendar (default)")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="show planned changes without touching the calendar or state")

    auth_parser = subparsers.add_parser("auth", help="interactive Google OAuth authorization")
    auth_parser.add_argument("--check", action="store_true",
                             help="report credential status without authorizing")

    subparsers.add_parser("status", help="show tracked posts and events from the last runs")
    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stderr,
    )


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
        source=source, extractor=extractor, sink=sink, state=state,
        config=config, dry_run=dry_run,
    )
    if not dry_run:
        save_state(state, config.state_path)
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


def main(argv: list[str] | None = None) -> int:
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
        return EXIT_CONFIG
    except Exception:
        logger.exception("Run failed")
        return EXIT_ERROR


def entry() -> None:
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v` — Expected: 6 passed.

- [ ] **Step 5: Smoke-test the real binary**

```powershell
ftmo-calendar --version
ftmo-calendar status
ftmo-calendar auth --check
```

Expected: version prints; status reports no runs; auth --check reports token state (or missing token instructions).

- [ ] **Step 6: Commit**

```powershell
git add src/ftmo_calendar/cli.py tests/test_cli.py
git commit -m "feat: CLI with run/auth/status, dry-run, and meaningful exit codes"
```

---

### Task 14: Documentation & examples

**Files:**
- Create: `config.example.toml`
- Modify: `.env.example`
- Create: `README.md` (rename from `README.MD`, full rewrite)
- Create: `CHANGELOG.md`
- Delete: `main.py`, `run.sh`, `IMPROVEMENTS.md` (superseded)

- [ ] **Step 1: Create `config.example.toml`**

```toml
# AutoFtmoCalendar configuration. Every key is optional — these are the defaults.
# Copy to config.toml and edit. Secrets do NOT go here; put them in .env.

[source]
url = "https://ftmo.com/en/trading-updates/"
keywords = ["maintenance", "market is closed", "ctrader", "holiday", "crypto"]
timezone = "Europe/Bucharest"   # assumed when the announcement states no offset
max_posts = 4                   # how many recent posts to process per run
max_age_days = 14               # ignore posts older than this

[llm]
# provider "gemini" uses Google AI Studio (free tier available).
# provider "openai-compatible" works with OpenRouter, OpenAI, Groq, Ollama, …
provider = "gemini"
base_url = ""                   # e.g. "https://openrouter.ai/api/v1" for OpenRouter
models = ["gemini-2.5-flash", "gemini-2.0-flash"]   # ordered fallback list
# The API key comes from the LLM_API_KEY environment variable (see .env.example).

[calendar]
auth_mode = "oauth"             # "oauth" (desktop) or "service_account" (servers; never expires)
name = "Trading"                # calendar found-or-created in oauth mode
calendar_id = ""                # REQUIRED for service_account; optional override for oauth
timezone = "Europe/Bucharest"
reminders_minutes = [60, 10]    # popup reminders before each event

[events]
max_duration_hours = 48         # sanity cap; longer extractions are rejected
max_days_ahead = 120

[events.summaries]
maintenance = "⚠️ FTMO Platform Maintenance"
crypto_closure = "🚫 Crypto Market Closed"
holiday_hours = "🕒 Modified Trading Hours"
other = "ℹ️ FTMO Trading Update"
```

- [ ] **Step 2: Rewrite `.env.example`**

```bash
# API key for the configured LLM provider.
# - Gemini (default): create a key at https://aistudio.google.com/apikey
# - OpenRouter: create a key at https://openrouter.ai/keys and set
#   [llm] provider/base_url in config.toml
LLM_API_KEY="your-key-here"

# Legacy name, still honored if LLM_API_KEY is unset:
# GEMINI_API_KEY="your-key-here"
```

- [ ] **Step 3: Write `README.md`** (rename: `git mv README.MD README.md`)

Structure (write real prose for each section):

```markdown
# AutoFtmoCalendar

> Never get caught by an FTMO maintenance window again.

[CI badge] [Python 3.11+ badge] [License badge]

Watches FTMO's trading updates page, extracts scheduled maintenance windows and
market closures with an LLM, and keeps a dedicated Google Calendar in sync —
including updating or removing events when FTMO reschedules an announcement.

## How it works            <- pipeline diagram (mermaid: Source -> LLM -> Validate -> Reconcile -> Calendar)
## Quickstart              <- pipx/pip install, .env + config.toml copy, `ftmo-calendar auth`, `ftmo-calendar run --dry-run`, `ftmo-calendar run`
## Choosing an LLM provider <- Gemini (default, free tier) vs OpenRouter/OpenAI/Groq/Ollama config snippets
## Google Calendar setup
###   Option A: OAuth (desktop)        <- credentials.json steps + IMPORTANT box: publish the
                                          OAuth consent screen to Production, otherwise Google
                                          expires refresh tokens every 7 days
###   Option B: Service account (servers, recommended for cron)
                                       <- create SA, download key as service_account.json, share
                                          calendar with SA email, set calendar_id in config.toml
## Scheduling              <- cron example + Windows Task Scheduler example; note exit codes (0 ok, 1 error, 2 config/auth)
## CLI reference           <- run [--dry-run] / auth [--check] / status / --config / -v
## How sync stays trustworthy <- content-hash caching, reconcile semantics, aftc_key extended property, validation rules
## Troubleshooting         <- token expired weekly -> Production publishing; scraper finds no posts -> page changed, open an issue; rate limits -> fallback models
## Disclaimer              <- personal project, not affiliated with FTMO
```

- [ ] **Step 4: Create `CHANGELOG.md`**

```markdown
# Changelog

## 0.2.0 — 2026-06-09

Complete rewrite as a professional package.

### Added
- `ftmo-calendar` CLI: `run` (with `--dry-run`), `auth` (with `--check`), `status`
- Provider-agnostic LLM parsing: Gemini or any OpenAI-compatible endpoint
  (OpenRouter, OpenAI, Groq, Ollama, …) via `[llm]` config
- Service-account auth mode: no browser, no token expiry — ideal for servers
- Reconcile sync: rescheduled/withdrawn announcements update or remove their
  calendar events instead of leaving stale duplicates
- Multi-post scraping matching FTMO's redesigned site (the old `trup-primary`
  selector no longer exists)
- Content-hash caching: unchanged posts cost zero LLM calls
- Event reminders, type-specific summaries, trimmed descriptions
- Validation: duration caps, date windows, timezone normalization from the
  announcement's stated offset
- Tests, ruff, mypy, GitHub Actions CI, TOML config

### Fixed
- Expired OAuth tokens no longer launch a browser flow inside cron (which hung
  forever on headless machines); `run` now fails loudly with instructions
- Documented the 7-day token death: OAuth apps in "Testing" status must be
  published to Production

### Removed
- `main.py` single-file script, `run.sh`, dev scrap scripts, committed `app.log`
```

- [ ] **Step 5: Delete superseded files and commit**

```powershell
git rm main.py run.sh IMPROVEMENTS.md
git mv README.MD README.md   # if not already done in step 3
git add -A
git commit -m "docs: professional README, config/env examples, changelog; drop legacy script"
```

---

### Task 15: CI, lockfile, final verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `requirements.lock`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: pip install -e .[dev]
      - name: Lint
        run: ruff check .
      - name: Format check
        run: ruff format --check .
      - name: Type check
        run: mypy src
      - name: Tests
        run: pytest -v
```

- [ ] **Step 2: Format and lint the whole codebase**

```powershell
ruff format .
ruff check --fix .
```

Fix any remaining findings by hand.

- [ ] **Step 3: Type-check**

Run: `mypy src` — Expected: no errors (add narrow `# type: ignore[...]` only where Google SDK types are missing).

- [ ] **Step 4: Full test suite**

Run: `pytest -v` — Expected: all tests pass (≈38).

- [ ] **Step 5: Generate the lockfile**

```powershell
pip freeze --exclude-editable | Out-File -Encoding utf8 requirements.lock
```

- [ ] **Step 6: End-to-end smoke test against the live site**

```powershell
ftmo-calendar run --dry-run
```

Expected: fetches the real FTMO page, extracts events with the configured LLM, prints planned creations, exits 0, calendar untouched. (Requires `LLM_API_KEY` in `.env`; auth is not needed for dry-run **only if** sink construction is skipped — it is not, so token/service account must be configured. If the user's token is currently expired this is the moment to run `ftmo-calendar auth`.)

- [ ] **Step 7: Commit and push**

```powershell
git add -A
git commit -m "ci: GitHub Actions lint/typecheck/test matrix and dependency lockfile"
git push origin main
```

---

## Plan self-review notes

- **Spec coverage:** secret purge (T1), packaging (T2), provider-agnostic LLM (T6-7), multi-post scraping (T5), state + caching (T9, T12), reconcile sync with `aftc_key` (T11-12), auth hardening incl. service account + no-interactive-in-run + `auth --check` + Production docs (T10, T14), reminders/summaries/descriptions (T8, T11), CLI with dry-run (T13), fail-loud exit codes (T13), tests/CI (every task + T15). README Production-publishing docs (T14). ✔
- **Type consistency:** `EventSink` protocol (find_event_id_by_key/create_event/delete_event) matches `GoogleCalendarSink` and the test `FakeSink`; `RawEvent` fields consistent across T6/T8/T12; `PostState(content_hash, last_seen, events)` consistent across T9/T12. ✔
- **Known judgment calls:** dry-run still calls the LLM (needed to show planned changes) and constructs the sink (needs auth); `parse_listing` returning no embedded post is a warning while zero posts overall is a hard `ScrapeError`; ended events are never deleted from the calendar (history preservation).
