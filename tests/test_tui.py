import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.watch import find_sources

pytest.importorskip("textual")

from textual.widgets import DataTable, Select  # noqa: E402

from cvforge.tui import CvforgeApp, Outcome, process, summarize  # noqa: E402

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = FIXTURES / "career_ops.html"


def test_process_runs_the_real_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outcome = process(SOURCE, "modern", 2)
    assert outcome.exit_code == 0, outcome.output
    assert outcome.report["theme"] == "modern" and outcome.report["fit"]["pages"] == 1
    headline, rows = summarize(outcome)
    assert headline == "1 page(s), limit 2: all checks passed"
    names = [name for name, _, _ in rows]
    assert "Faithfulness: Coverage" in names and "ATS: PDF hygiene" in names
    assert ("Page fit", "PASS", "theme as designed") in rows
    assert not [row for row in rows if row[1] == "FAIL"]


def test_summarize_reports_each_kind_of_failure():
    unreadable = Outcome(2, {}, "wrote nothing\nCannot ingest cv.html: name missing\n")
    assert summarize(unreadable) == (
        "Could not process this file: Cannot ingest cv.html: name missing",
        [],
    )

    failed = {"name": "No additions", "status": "fail", "details": ["summary: 'made up'"]}
    unverified = Outcome(1, {"verify": {"passed": False, "checks": [failed]}}, "")
    headline, rows = summarize(unverified)
    assert headline == "Verification failed, so nothing was rendered."
    assert rows == [("Faithfulness: No additions", "FAIL", "summary: 'made up'")]

    fit = {"pages": 2, "limit": 1, "fits": False, "adjustments": {}, "lines_over": 4}
    too_long = Outcome(
        1,
        {"verify": {"checks": []}, "fit": fit, "lint": ["a", "b"], "ingest": {"unplaced": ["x"]}},
        "",
    )
    headline, rows = summarize(too_long)
    assert headline == "2 page(s), limit 1: a check FAILED"
    assert rows == [
        ("Page fit", "FAIL", "about 4 line(s) over; nothing was dropped"),
        ("Lint", "WARN", "2 warning(s)"),
        ("Kept verbatim, not mapped", "WARN", "x"),
    ]


def test_app_shows_results_and_reruns_when_the_theme_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario() -> tuple[str, int, str, str]:
        tui = CvforgeApp([SOURCE], ["classic", "modern"], "classic", 2)
        async with tui.run_test() as pilot:
            await tui.workers.wait_for_complete()
            await pilot.pause()
            first, row_count = tui.headline, tui.query_one(DataTable).row_count
            tui.query_one("#theme", Select).value = "modern"
            await pilot.pause()
            working = tui.headline
            await tui.workers.wait_for_complete()
            await pilot.pause()
            return first, row_count, working, tui.headline

    first, row_count, working, second = asyncio.run(scenario())
    assert first == "1 page(s), limit 2: all checks passed"
    assert row_count >= 10  # five faithfulness rows, the ATS rows, page fit and lint
    assert working.startswith("Working on career_ops.html (modern")
    assert second == first
    report = (tmp_path / "out" / "career_ops" / "report.json").read_text(encoding="utf-8")
    assert '"theme": "modern"' in report


def test_tui_command_needs_resumes(tmp_path):
    result = runner.invoke(app, ["tui", str(tmp_path)])
    assert result.exit_code == 2 and "No .html or .tex files" in result.output


def test_find_sources_skips_outputs_and_hidden_folders(tmp_path):
    for folder in ("in", "out", ".venv/lib", "node_modules/x"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "cv.html").write_text("<html></html>", encoding="utf-8")
    assert find_sources(tmp_path) == [tmp_path / "in" / "cv.html"]
