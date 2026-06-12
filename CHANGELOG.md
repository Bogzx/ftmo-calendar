# Changelog

## 0.8.1 — 2026-06-12

### Fixed
- ICS feed times no longer render as UTC `Z` timestamps. Events are now
  written as local times in the calendar's timezone (`[calendar] timezone`,
  default `Europe/Bucharest` — FTMO platform time) with a `TZID` reference and
  a generated `VTIMEZONE` block carrying the real DST rules, plus an
  `X-WR-TIMEZONE` calendar header. Timezone-aware clients show the identical
  instant they always did (converted to each viewer's local time), but clients
  that mishandle the `Z` suffix — which made a 9:00 GMT+3 maintenance window
  appear at 6:00 — now read FTMO's announced wall-clock times directly. The
  raw feed also matches the announcements again instead of being shifted
  three hours for everyone east of Greenwich.

## 0.8.0 — 2026-06-10

Granular event taxonomy (grounded in FTMO's announcement history) + stats.

### Added
- Seven event types replacing the coarse four: `maintenance`, `crypto_closure`,
  `holiday_closure`, `early_close`, `late_open`, `symbol_event`, `other`
  (`holiday_hours` remains valid for pre-0.8 state files). Derived from a
  sample of historical FTMO posts; verified live: the Memorial Day announcement
  extracts as 8 correctly-typed events with zero rejections
- Event titles now carry the affected symbols/platforms ("⏳ Early Close —
  US30.cash, US100.cash"), extracted via a new `affected` field; consensus
  voting merges partial symbol lists, keeping the most complete
- Prompt now explicitly ignores leverage adjustments, execution-model news,
  and permanent session-time changes
- Landing page: seven filter chips
- Self-hosted anonymous statistics in serve mode: page views, unique visitors
  (random-id first-party cookie), feed pulls, unique feed clients; footer
  summary, `GET /stats` JSON with 30-day history, persisted to `stats.json`

## 0.7.0 — 2026-06-10

Per-interest feeds: subscribe to only what you trade.

### Added
- Type-filtered feeds in serve mode: `/feed.ics?types=crypto_closure` (any
  comma-separated combination of `maintenance`, `crypto_closure`,
  `holiday_hours`, `other`); each URL acts as its own calendar; unknown types
  return a 400 listing valid ones; filtered calendars are named after their
  filter
- Landing page filter chips: untick event types and the subscribe URL (and
  webcal link) rebuild live
- Tracked events store their event type (state v3; older state files load
  transparently — pre-v3 events appear only in the unfiltered feed until they
  regenerate)

## 0.6.0 — 2026-06-09

A real landing page for hosted deployments.

### Added
- The served `/` and `/status` page is now a designed, self-contained landing
  page (trading-terminal aesthetic, no external requests): live countdown to
  the next interruption, all times rendered in the visitor's local timezone,
  one-click feed URL copy + `webcal://` open, per-app subscribe instructions,
  upcoming/in-progress/past schedule, sync health footer
- Works without JavaScript (UTC times as fallback); responsive down to phones

## 0.5.0 — 2026-06-09

Deterministic extraction, verified live on DeepSeek via OpenRouter.

### Added
- **Consensus voting** (`[llm] consensus_runs`, default 3): each changed post is
  extracted N times and only majority events are kept — stable results even on
  hosted APIs that aren't deterministic at temperature 0 (OpenRouter routes one
  model id across several providers). Verified live: 4 consecutive consensus
  extractions of a real FTMO post produced identical event sets.
- Prompt rule excluding Client Area/IT/account-services maintenance (the one
  borderline case that flickered between runs) — only trading interruptions count
- `seed` hint on OpenAI-compatible calls for providers that honor it
- Consensus identity merges timezone-attribution variants of the same event,
  preferring the explicit offset

## 0.4.0 — 2026-06-09

Feed-first hosting: run a public feed for a whole group with just an LLM key.

### Added
- **Feed-only mode** (`[calendar] enabled = false`): no Google account needed
  anywhere — the host runs one container, subscribers paste a URL
- `--dry-run` no longer requires Google credentials (preview before any setup)
- Status page upgraded into a shareable landing page: next upcoming event,
  sync health, and per-app subscribe instructions
- `/healthz` now reports `next_run` so monitors can detect overdue syncs
- ICS feed: `REFRESH-INTERVAL`/`X-PUBLISHED-TTL` hints and per-event source
  links in descriptions
- Docker `HEALTHCHECK` against `/healthz`

### Fixed
- Config and state files written by Notepad/PowerShell (UTF-8 BOM) parse
  correctly instead of failing with a cryptic TOML error
- Serve mode writes the feed from existing state at startup — a restart with a
  failing sync no longer 404s the feed
- A persistent identical sync error notifies once, not every interval

## 0.3.0 — 2026-06-09

Reach & visibility: notifications, ICS feed, hosted mode, Docker.

### Added
- Discord webhook and Telegram bot notifications: new/removed events, run
  failures, and an optional periodic heartbeat (`[notify] heartbeat_hours`)
- ICS feed export (`[ics] enabled`): subscribe from any calendar app with
  zero OAuth setup
- `ftmo-calendar serve`: periodic sync loop + HTTP server exposing
  `/feed.ics`, a `/status` page, and `/healthz` — host one feed for a whole
  trading group; a failing sync never takes the feed down
- Docker support: `docker compose up -d` runs serve mode with all runtime
  files in a `./data` volume
- State v2: tracked events carry display data; heartbeat timestamp persisted
  (v1 state files load transparently)

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
