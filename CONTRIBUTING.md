# Contributing

Thanks for considering a contribution!

## Development setup

```bash
git clone https://github.com/Bogzx/AutoFtmoCalendar && cd AutoFtmoCalendar
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

## Before opening a PR

All three must pass — CI runs the same checks:

```bash
ruff check . && ruff format --check .
mypy src
pytest
```

- New behavior needs a test. The suite runs offline: scraping is tested against
  recorded HTML fixtures (`tests/fixtures/`), LLM parsing against scripted
  backends, and the HTTP server against a real server on an ephemeral port.
- Keep the pipeline seams: new announcement sources implement the `Source`
  protocol (`sources/`), new calendar targets implement `EventSink` (`sinks/`),
  new notification channels implement `Notifier` (`notify/`).
- Architecture and design history live in `docs/superpowers/specs/` and
  `docs/superpowers/plans/`.

## Adding a new prop-firm source

Open an issue first with the firm's announcements URL — source support is
demand-driven and we'd like to record real demand before merging code for it.
