"""Terminal UI (`pip install cvforge[tui]`): pick a resume, a theme and a page limit, and
see the page count and every check for that combination.

Each change runs the ordinary `cvforge run` in a subprocess and shows its report.json, so the
TUI can never disagree with the command line.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Label, OptionList, Select, Static

Row = tuple[str, str, str]
_STYLE = {"PASS": "green", "WARN": "yellow", "FAIL": "bold red", "INFO": "cyan"}


@dataclass
class Outcome:
    exit_code: int
    report: dict[str, Any]
    output: str


def process(source: Path, theme: str, pages: int) -> Outcome:
    """Run the whole pipeline for one source and collect its report."""
    report_path = Path("out") / source.stem / "report.json"
    report_path.unlink(missing_ok=True)  # never show a report left over from an earlier run
    command = [sys.executable, "-m", "cvforge", "run", str(source)]
    done = subprocess.run(
        [*command, "--theme", theme, "--pages", str(pages)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return Outcome(done.returncode, report, done.stdout + done.stderr)


def summarize(outcome: Outcome) -> tuple[str, list[Row]]:
    """A one-line headline and (check, result, details) rows for an outcome."""
    report = outcome.report
    rows: list[Row] = []
    for label, key in (("Faithfulness", "verify"), ("ATS", "check")):
        for check in report.get(key, {}).get("checks", []):
            details = "; ".join(check["details"])
            rows.append((f"{label}: {check['name']}", check["status"].upper(), details))
    if fit := report.get("fit"):
        changes = ", ".join(f"{token} {change}" for token, change in fit["adjustments"].items())
        over = f"about {fit['lines_over']} line(s) over; nothing was dropped"
        details = changes or "theme as designed" if fit["fits"] else over
        rows.append(("Page fit", "PASS" if fit["fits"] else "FAIL", details))
    if "lint" in report:
        count = len(report["lint"])
        rows.append(("Lint", "WARN" if count else "PASS", f"{count} warning(s)"))
    if unplaced := report.get("ingest", {}).get("unplaced"):
        rows.append(("Kept verbatim, not mapped", "WARN", "; ".join(unplaced)))

    if not report.get("verify"):
        lines = [line.strip() for line in outcome.output.splitlines() if line.strip()]
        return f"Could not process this file: {lines[-1] if lines else 'no output'}", rows
    if not fit:
        return "Verification failed, so nothing was rendered.", rows
    verdict = "all checks passed" if outcome.exit_code == 0 else "a check FAILED"
    return f"{fit['pages']} page(s), limit {fit['limit']}: {verdict}", rows


class CvforgeApp(App[None]):
    TITLE = "cvforge"
    BINDINGS = [("q", "quit", "Quit"), ("r", "rerun", "Run again")]
    CSS = """
    #pick { width: 44; padding: 0 1; }
    #files { height: 1fr; }
    #result { padding: 0 1; }
    #headline { height: 3; content-align: left middle; text-style: bold; }
    Label { margin-top: 1; color: $text-muted; }
    """

    def __init__(self, sources: list[Path], themes: list[str], theme: str, pages: int) -> None:
        super().__init__()
        self.sources, self.themes = sources, themes
        self.theme_name, self.pages = theme, pages
        self.source: Path | None = None
        self.headline = ""
        self.rows: list[Row] = []
        self._ticket = 0  # only the newest run may update the screen

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="pick"):
                yield Label("Resume (Enter to choose)")
                yield OptionList(*(str(source) for source in self.sources), id="files")
                yield Label("Theme")
                themes = [(name, name) for name in self.themes]
                yield Select(themes, value=self.theme_name, allow_blank=False, id="theme")
                yield Label("Page limit")
                limits = [(str(n), n) for n in sorted({1, 2, 3, self.pages})]
                yield Select(limits, value=self.pages, allow_blank=False, id="pages")
            with Vertical(id="result"):
                yield Static("", id="headline")
                yield DataTable(id="checks", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Check", "Result", "Details")
        if self.sources:
            self.source = self.sources[0]
            self.action_rerun()

    @on(OptionList.OptionSelected, "#files")
    def _file_chosen(self, event: OptionList.OptionSelected) -> None:
        self.source = self.sources[event.option_index]
        self.action_rerun()

    @on(Select.Changed)
    def _setting_changed(self, event: Select.Changed) -> None:
        before = (self.theme_name, self.pages)
        if event.select.id == "theme":
            self.theme_name = str(event.value)
        else:
            self.pages = int(event.value)  # type: ignore[arg-type]
        if (self.theme_name, self.pages) != before:
            self.action_rerun()

    def action_rerun(self) -> None:
        if self.source is None:
            return
        self._ticket += 1
        self._show(
            f"Working on {self.source.name} ({self.theme_name}, {self.pages} page(s))...", []
        )
        self._run(self._ticket, self.source, self.theme_name, self.pages)

    @work(thread=True)
    def _run(self, ticket: int, source: Path, theme: str, pages: int) -> None:
        outcome = process(source, theme, pages)
        self.call_from_thread(self._finish, ticket, outcome)

    def _finish(self, ticket: int, outcome: Outcome) -> None:
        if ticket == self._ticket:  # a newer run has started otherwise
            self._show(*summarize(outcome))

    def _show(self, headline: str, rows: list[Row]) -> None:
        self.headline, self.rows = headline, rows
        self.query_one("#headline", Static).update(headline)
        table = self.query_one(DataTable)
        table.clear()
        for name, status, details in rows:
            table.add_row(name, f"[{_STYLE.get(status, 'white')}]{status}[/]", details)
