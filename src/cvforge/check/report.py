"""Show check and lint results as Rich tables, and save them as report.json."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from cvforge.check.ats import CheckResult
from cvforge.lint import LintWarning

_STYLE = {"pass": "green", "warn": "yellow", "fail": "bold red", "info": "cyan"}


def print_checks(results: list[CheckResult], console: Console, title: str = "ATS check") -> None:
    table = Table(title=title, title_justify="left", show_lines=True)
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Details", overflow="fold")
    for result in results:
        status = f"[{_STYLE[result.status]}]{result.status.upper()}[/]"
        table.add_row(result.name, status, escape("\n".join(result.details)))
    console.print(table)


def print_lint(warnings: list[LintWarning], console: Console) -> None:
    if not warnings:
        console.print("[green]lint: no warnings[/green]")
        return
    table = Table(title=f"Lint: {len(warnings)} warning(s)", title_justify="left")
    table.add_column("Where")
    table.add_column("Rule")
    table.add_column("Warning", overflow="fold")
    for warning in warnings:
        table.add_row(warning.location, warning.rule, escape(warning.message))
    console.print(table)


def check_section(
    pdf: Path | None, results: list[CheckResult], extractors: list[str] | None = None
) -> dict[str, Any]:
    """One stage's results in the shape report.json stores them."""
    section: dict[str, Any] = {
        "passed": not any(result.status == "fail" for result in results),
        "checks": [asdict(result) for result in results],
    }
    if pdf:
        section = {"pdf": pdf.name, "extractors": extractors, **section}
    return section


def update_report(path: Path, **sections: Any) -> None:
    """Merge sections into report.json, keeping what earlier stages wrote."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no report yet, or one damaged by hand: start afresh
        report = {}
    if not isinstance(report, dict):
        report = {}
    report.update(sections)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
