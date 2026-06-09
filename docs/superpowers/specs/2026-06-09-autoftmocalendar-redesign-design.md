# AutoFtmoCalendar Redesign — Design Document

Date: 2026-06-09
Status: Awaiting user approval

## 1. Vision and scope

AutoFtmoCalendar watches FTMO's trading-updates page and keeps a Google Calendar
in sync with announced maintenance windows and market closures, so traders are
never surprised by a platform outage. The product stays FTMO-focused; the
internals are built as a `Source → Parser → Sink` pipeline so additional
sources (other prop firms) and sinks (ICS feed) are additive modules later, not
rewrites.

The defining quality goal: **a trader must be able to trust the calendar.**
Everything in Phase 1 serves that — deterministic parsing, true sync semantics
(including rescheduled and removed announcements), full page coverage, and loud
failure.

Out of scope (deliberately): web dashboard, historical announcement database,
Outlook/CalDAV API sinks, multi-firm sources (the seam exists; the sources
don't), hosted service (possible Phase 3 layer).

## 2. Core behavior: trustworthy sync

### 2.1 Coverage — parse all posts, not the first

The current scraper reads only `div.trup-primary` (the featured post). The new
`FtmoSource` extracts **every update post** on the page as a separate
`SourcePost {post_key, text}`, where `post_key` is a stable identifier (the
post's permalink/anchor if present, else a hash of its heading). Fallback: if
individual posts cannot be isolated (page structure change), treat the whole
page as one post and emit a warning. Keyword filtering applies per post.

### 2.2 Reschedule/cancel handling — per-post reconcile

State file (`state.json`, in a configurable data dir) maps:

```
post_key → { content_hash, events: [ { event_key, google_event_id } ] }
```

Per run, per post:
- **Hash unchanged** → skip (no AI call, no calendar call).
- **Hash changed or post is new** → parse with AI, then reconcile against the
  post's previous events:
  - parsed event matches a stored `event_key` → keep (update if details drifted)
  - stored event no longer present in the new parse → **delete** the Google
    event (the announcement was rescheduled or withdrawn)
  - new event → create
- **Post disappeared from page** → keep its events (FTMO rotates old posts off
  the page; absence is not cancellation). Prune state entries whose events have
  all ended.

`event_key = sha256(post_key | event_type | start_iso | end_iso)[:16]`. The key
is also written to the Google event's `extendedProperties.private.aftc_key`, so
dedup survives a lost state file: before creating, query the calendar by
`privateExtendedProperty=aftc_key=...` (no 7-day window limitation).

### 2.3 Deterministic parsing

- Migrate from the deprecated `google-generativeai` SDK to **`google-genai`**.
- `temperature=0`, structured output via `response_schema` (Pydantic model),
  not just JSON mime type. Schema per event:
  `{event_type: enum[maintenance, crypto_closure, holiday_hours, other],
    start_time, end_time, stated_utc_offset, confidence: enum[high, low]}`.
- Model list (ordered fallback) comes from config, not code.
- Validation rules (reject + log + flag the post as needs-attention):
  - `end > start`
  - duration ≤ 48h (configurable)
  - start within `[now − 30d, now + 120d]`
  - if `stated_utc_offset` missing, assume `source_timezone` from config.
- Recorded-HTML fixtures + golden-file expected outputs make parsing testable
  without live API calls.

### 2.4 Calendar event quality

- Type-specific summaries via config templates, defaults:
  `⚠️ cTrader Maintenance`, `🚫 Crypto Market Closed`, `🕒 Modified Trading
  Hours`, `ℹ️ FTMO Trading Update`.
- Description: trimmed excerpt of the relevant post (not the whole page) + link
  to the FTMO updates page + attribution line.
- **Reminders**: popup at 60 and 10 minutes before start (configurable list).
- Times stored timezone-aware; source timezone and calendar timezone both
  configurable (defaults preserve current behavior: Europe/Bucharest).

### 2.5 Fail loudly

- Retries (3, backoff) only for *typed transient* errors: network timeouts,
  HTTP 429/5xx, Gemini rate limits.
- Everything else propagates to the pipeline top: clear log message, **non-zero
  exit code** so cron/Docker/systemd can detect failure.
- Scraper finding zero posts is an **error**, not an info log (the page
  structure changed — the exact silent-death scenario to prevent).
- `notify/` package defines the hook (Phase 2 fills in Discord/Telegram).

## 3. Architecture

```
src/ftmo_calendar/
  cli.py              # entry: run [--dry-run], auth, status
  config.py           # config.toml + env-var overrides, validated at startup
  models.py           # SourcePost, TradingEvent, enums
  pipeline.py         # fetch → cache-check → parse → validate → reconcile → notify
  state.py            # state.json load/save, pruning
  sources/
    base.py           # Source protocol: fetch() -> list[SourcePost]
    ftmo.py
  parsing/
    gemini.py         # google-genai, schema-enforced, temp 0
    validate.py
  sinks/
    base.py           # Sink protocol: reconcile(post_key, events) -> SyncResult
    google_calendar.py
  notify/
    base.py           # Notifier protocol (implementations in Phase 2)
tests/
  fixtures/           # recorded FTMO HTML, golden parse JSON
```

- **CLI** (`ftmo-calendar` console script): `run` (default), `run --dry-run`
  (prints planned creates/updates/deletes, touches nothing), `auth` (runs the
  OAuth flow explicitly instead of as a side effect), `status` (last run time,
  last content hashes, tracked events).
- **Config**: `config.toml` (keywords, calendar name, timezones, model list,
  summary templates, reminders, data dir) with env-var overrides; secrets
  (`GEMINI_API_KEY`) stay in `.env`/environment. Ship `config.example.toml`
  and a complete `.env.example`.
- **Data model** (`TradingEvent`): `event_key, event_type, summary, start, end
  (aware datetimes), source_post_key, source_url, excerpt`.

## 4. Repo professionalism

- 🚨 **Secret hygiene**: `app.log` is committed and contains an OAuth
  authorization code. Remove it, gitignore it, purge from git history
  (`git filter-repo`), force-push, and revoke/re-grant the app in Google
  account settings.
- **Packaging**: `pyproject.toml` (src layout, console entry point,
  Python ≥3.10), pinned lock for reproducible installs.
- **Quality gates**: ruff (lint+format), mypy, pytest; GitHub Actions running
  all three on push/PR.
- **Cleanup**: delete `check_models.py`, `test_generation.py`; fix README typos;
  complete `.env.example`.
- **Docker** (Phase 2): Dockerfile + compose with `CHECK_INTERVAL` loop, so
  non-developers run `docker compose up -d` instead of configuring cron.
- **README overhaul** (Phase 2): badges, calendar screenshot, 5-minute
  quickstart (Docker first, pipx second), architecture diagram,
  troubleshooting/FAQ. CHANGELOG + tagged releases from Phase 1 on.

## 5. Phased roadmap

**Phase 1 — the trustworthy sync core** (this design's implementation target)
1. Secret purge + .gitignore fix
2. Package restructure (src layout, modules above), pyproject, pinned deps
3. `google-genai` migration: schema-enforced, temp-0 parsing + validation
4. Multi-post scraping with per-post keys
5. State file + per-post content-hash caching
6. Reconcile sync (create/update/delete via `aftc_key` extended property)
7. Reminders + type-specific summaries + trimmed descriptions
8. CLI (`run`, `--dry-run`, `auth`, `status`), fail-loud error handling
9. Tests (fixtures + golden files), ruff/mypy/pytest CI

Done = same product, but parsing is deterministic, reschedules are handled,
nothing is silently missed, and the repo installs and reads like a real project.

**Phase 2 — reach and visibility**: Discord webhook notifications (new events,
errors, heartbeat), Docker compose, ICS file sink, README overhaul with visuals.

**Phase 3 — optional growth**: hosted public ICS feed + status page; additional
prop-firm sources if demand appears.
