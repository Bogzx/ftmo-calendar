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
