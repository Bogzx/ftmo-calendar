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
