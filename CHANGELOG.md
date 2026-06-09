# Changelog

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
