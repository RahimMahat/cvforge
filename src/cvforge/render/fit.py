"""Fit a resume to a page limit by tightening layout tokens. Content is never dropped."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

from cvforge.render.typst_renderer import load_theme, render_pdf
from cvforge.render.view import flatten

MAX_COMPILES = 8
MIN_LAST_PAGE_FILL = 0.15
# How far fitting may go. Body size and margin may dip below a theme's normal range.
FLOORS = {
    "section_gap": 10,
    "entry_gap": 6,
    "item_gap": 2,
    "line_height": 1.2,
    "body_size": 9.5,
    "margin": 12,
}
_MM = 72 / 25.4  # points per millimetre


@dataclass
class FitReport:
    pages: int
    limit: int
    fits: bool
    compiles: int
    adjustments: dict[str, str] = field(default_factory=dict)  # token -> "10.5 -> 10"
    lines_over: int = 0
    longest_sections: list[str] = field(default_factory=list)
    longest_bullets: list[str] = field(default_factory=list)
    last_page_fill: float = 1.0
    warnings: list[str] = field(default_factory=list)


def steps(theme: dict[str, Any]) -> list[dict[str, float]]:
    """Cumulative token overrides, gentlest first: spacing, line height, body size, margins."""
    current: dict[str, float] = {}
    out: list[dict[str, float]] = []

    def lower(**tokens: float) -> None:
        changed = {k: v for k, v in tokens.items() if v < current.get(k, theme[k])}
        if changed:
            current.update(changed)
            out.append(dict(current))

    lower(**{k: FLOORS[k] for k in ("section_gap", "entry_gap", "item_gap")})
    lower(line_height=FLOORS["line_height"])
    for token, step in (("body_size", 0.5), ("margin", 2)):
        value = theme[token]
        while value > FLOORS[token]:
            value = max(FLOORS[token], value - step)
            lower(**{token: value})
    return out[: MAX_COMPILES - 1]  # the first compile is the theme as designed


def _measure(pdf: Path, limit: int, margin_mm: float) -> tuple[int, int, float]:
    """(pages, text lines beyond the limit, how full the last page is from 0 to 1)."""
    with pdfplumber.open(pdf) as doc:
        pages = doc.pages
        over = sum(len((page.extract_text() or "").splitlines()) for page in pages[limit:])
        last, margin = pages[-1], margin_mm * _MM
        bottom = max((word["bottom"] for word in last.extract_words()), default=margin)
        fill = (bottom - margin) / (last.height - 2 * margin)
        return len(pages), over, max(0.0, min(1.0, fill))


def _longest(view: dict[str, Any]) -> tuple[list[str], list[str]]:
    sizes: dict[str, int] = {}
    bullets: list[str] = []
    heading = ""
    for kind, text in flatten(view):
        if kind == "heading":
            heading = text
        elif heading:
            sizes[heading] = sizes.get(heading, 0) + len(text)
            if kind == "bullet":
                bullets.append(text)
    sections = sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:3]
    longest = sorted(bullets, key=len, reverse=True)[:3]
    return (
        [f"{name} ({size} characters)" for name, size in sections],
        [f"{len(b)} characters: {b[:70]}..." for b in longest],
    )


def fit(view: dict[str, Any], theme: str, paper: str, out: Path, limit: int) -> FitReport:
    """Render `out`, tightening the layout only as far as needed to reach `limit` pages."""
    tokens = load_theme(theme)
    render_pdf(view, theme, paper, out)
    pages, over, fill = _measure(out, limit, tokens["margin"])
    report = FitReport(pages, limit, pages <= limit, compiles=1)

    if not report.fits:
        for overrides in steps(tokens):
            render_pdf(view, theme, paper, out, overrides)
            report.compiles += 1
            margin = overrides.get("margin", tokens["margin"])
            pages, over, fill = _measure(out, limit, margin)
            if pages <= limit:
                report.fits = True
                report.adjustments = {k: f"{tokens[k]} -> {v}" for k, v in overrides.items()}
                break
        else:
            # Cannot fit: say by how much at the tightest layout, then keep the designed one.
            report.lines_over = over
            report.longest_sections, report.longest_bullets = _longest(view)
            render_pdf(view, theme, paper, out)
            report.compiles += 1
            pages, _, fill = _measure(out, limit, tokens["margin"])

    report.pages, report.last_page_fill = pages, round(fill, 2)
    if fill < MIN_LAST_PAGE_FILL:
        report.warnings.append(
            f"the last page is only {fill:.0%} full; a tighter theme or --pages {pages - 1} "
            "may read better"
            if pages > 1
            else f"the page is only {fill:.0%} full"
        )
    return report
