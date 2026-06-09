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

### 2.3 Deterministic parsing — provider-agnostic LLM layer

- The parser depends on an `LLMClient` protocol, not a vendor SDK. Two backends:
  - **`openai-compatible`** (the `openai` package with a configurable
    `base_url`): covers OpenRouter, OpenAI, Groq, Mistral, Together, Ollama,
    and any other OpenAI-protocol endpoint. Uses JSON response format where the
    provider supports it; otherwise plain JSON instructions.
  - **`gemini`** (the current `google-genai` SDK, replacing the deprecated
    `google-generativeai`): native `response_schema` structured output.
- Config selects the backend:
  `[llm] provider = "openai-compatible" | "gemini"`, `base_url`, `models`
  (ordered fallback list), `api_key` read from the `LLM_API_KEY` env var
  (`GEMINI_API_KEY` still honored for backward compatibility).
- `temperature=0` everywhere. Output is validated with a Pydantic schema
  **regardless of provider**; on validation failure, one repair retry sends the
  validation error back to the model, then the fallback model is tried. Schema
  per event:
  `{event_type: enum[maintenance, crypto_closure, holiday_hours, other],
    start_time, end_time, stated_utc_offset, confidence: enum[high, low]}`.
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

### 2.5 Google Calendar auth that doesn't rot

Two auth modes, selected in config:

- **`service_account` (recommended for servers/cron):** the user creates a
  service account, shares the target calendar with the service account's email
  ("Make changes to events"), and sets `calendar_id` in config. No browser, no
  token refresh, **nothing ever expires**. The `auth --check` command verifies
  the account can see the calendar.
- **`oauth` (desktop use):** the current flow, hardened:
  - Interactive browser auth happens **only** in the explicit
    `ftmo-calendar auth` command — never as a side effect of `run`. (Today an
    expired token inside cron silently launches `run_local_server`, which
    blocks forever on a headless machine.)
  - On `RefreshError` during `run`: exit non-zero with an actionable message
    ("run `ftmo-calendar auth` to re-authorize") and fire the notifier hook.
  - `auth --check` reports token health: valid/expired, scopes, expiry time.
  - README documents the root cause of weekly token death: OAuth apps left in
    **"Testing" publishing status get 7-day refresh tokens**. Setup
    instructions walk through publishing the app to Production (no Google
    verification needed for personal use), which makes refresh tokens
    long-lived.

### 2.6 Fail loudly

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
    llm.py            # LLMClient protocol + extraction prompt + repair retry
    openai_compat.py  # OpenRouter/OpenAI/Groq/Ollama/... via base_url
    gemini.py         # google-genai native structured output
    validate.py
  sinks/
    base.py           # Sink protocol: reconcile(post_key, events) -> SyncResult
    google_calendar.py
    auth.py           # oauth + service-account credential providers, auth --check
  notify/
    base.py           # Notifier protocol (implementations in Phase 2)
tests/
  fixtures/           # recorded FTMO HTML, golden parse JSON
```

- **CLI** (`ftmo-calendar` console script): `run` (default), `run --dry-run`
  (prints planned creates/updates/deletes, touches nothing), `auth` (runs the
  OAuth flow explicitly instead of as a side effect), `status` (last run time,
  last content hashes, tracked events).
- **Config**: `config.toml` (keywords, calendar name/id, auth mode, timezones,
  LLM provider/base_url/models, summary templates, reminders, data dir) with
  env-var overrides; secrets (`LLM_API_KEY`, legacy `GEMINI_API_KEY`) stay in
  `.env`/environment. Ship `config.example.toml`
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
3. Provider-agnostic LLM layer (OpenAI-compatible + Gemini backends),
   schema-validated temp-0 parsing + validation + repair retry
4. Multi-post scraping with per-post keys
5. State file + per-post content-hash caching
6. Reconcile sync (create/update/delete via `aftc_key` extended property)
7. Auth hardening: service-account mode, oauth-only-in-`auth`-command,
   `auth --check`, Production-publishing docs
8. Reminders + type-specific summaries + trimmed descriptions
9. CLI (`run`, `--dry-run`, `auth`, `status`), fail-loud error handling
10. Tests (fixtures + golden files), ruff/mypy/pytest CI

Done = same product, but parsing is deterministic, reschedules are handled,
nothing is silently missed, and the repo installs and reads like a real project.

**Phase 2 — reach and visibility**: Discord webhook notifications (new events,
errors, heartbeat), Docker compose, ICS file sink, README overhaul with visuals.

**Phase 3 — optional growth**: hosted public ICS feed + status page; additional
prop-firm sources if demand appears.
