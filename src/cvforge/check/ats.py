"""ATS checks on a rendered PDF. Each check reports pass, warn or fail; there is no score."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader
from rapidfuzz import fuzz

from cvforge.check.extract_text import REQUIRED_EXTRACTORS, extract_all
from cvforge.config import Config
from cvforge.models import Resume
from cvforge.render.view import HEADINGS, build_view, display_url, flatten
from cvforge.textnorm import normalize, tech_tokens

Status = Literal["pass", "warn", "fail", "info"]

FUZZY_MIN = 95
PAGE_SIZES = {"a4": (595.28, 841.89), "us-letter": (612.0, 792.0)}  # pt
STANDARD_HEADINGS = set(HEADINGS.values())
_LIGATURES = "ﬀﬁﬂﬃﬄﬅﬆ"
_PROPER_RE = re.compile(r"(?<=[a-z,;:] )[A-Z][a-z]{2,}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,16}\d")  # +91 90000 00000, 090000 00000, (020) 1234 5678
_BROKEN_WORD_RE = re.compile(r"[A-Za-z]-\n\s*[a-z]")


@dataclass
class CheckResult:
    name: str
    status: Status
    details: list[str] = field(default_factory=list)


def _result(name: str, problems: list[str], severity: Status = "fail") -> CheckResult:
    return CheckResult(name, severity if problems else "pass", problems)


def _each(texts: dict[str, str], check: Callable[[str], list[str]]) -> list[str]:
    """Run a text check against every extractor's output, labelling what each one found."""
    return [f"[{name}] {problem}" for name, text in texts.items() for problem in check(text)]


def name_problems(name: str, text: str) -> list[str]:
    first = [line.strip() for line in text.splitlines() if line.strip()][:2]
    if normalize(name) in normalize(" ".join(first)):
        return []
    return [f"name {name!r} not in the first 2 lines: {first!r}"]


def contact_problems(resume: Resume | None, text: str) -> list[str]:
    """Email, phone and link text must survive extraction as plain text."""
    if resume is None:
        missing = [] if _EMAIL_RE.search(text) else ["no email address found"]
        return missing + ([] if _PHONE_RE.search(text) else ["no phone number found"])
    squashed = normalize(text).replace(" ", "")  # a long URL may wrap across lines
    basics = resume.basics
    shown = [basics.email, basics.phone, *(ln.text or display_url(ln.url) for ln in basics.links)]
    return [
        f"not extractable: {value!r}"
        for value in shown
        if value and normalize(value).replace(" ", "") not in squashed
    ]


def link_target_problems(resume: Resume, pdf: Path) -> list[str]:
    """Every link must be clickable through to its full URL."""
    targets = {
        str(annot.get_object().get("/A", {}).get("/URI", ""))
        for page in PdfReader(pdf).pages
        for annot in page.get("/Annots") or []
    }
    urls = [ln.url for ln in resume.basics.links] + [p.url for p in resume.projects if p.url]
    return [f"no clickable link to {url!r}" for url in urls if url not in targets]


def content_problems(expected: list[tuple[str, str]], text: str) -> tuple[list[str], list[str]]:
    """(missing, out of order): every expected item should appear, in reading order."""
    hay = normalize(text)
    cursor = 0
    missing, misplaced = [], []
    for kind, raw in expected:
        needle = normalize(raw)
        if not needle:
            continue
        start = hay.find(needle, cursor)
        end = start + len(needle)
        if start < 0:
            match = fuzz.partial_ratio_alignment(needle, hay[cursor:])
            if match and match.score >= FUZZY_MIN:
                start, end = cursor + match.dest_start, cursor + match.dest_end
        if start >= 0:
            cursor = end
            continue
        elsewhere = needle in hay or fuzz.partial_ratio(needle, hay) >= FUZZY_MIN
        (misplaced if elsewhere else missing).append(f"{kind}: {raw!r}")
    return missing, misplaced


def _content_results(expected: list[tuple[str, str]], texts: dict[str, str]) -> list[CheckResult]:
    """Missing text fails everywhere. Reading order must hold in the row-wise extractors;
    pdftotext -layout guesses columns, so a different order there is a warning."""
    failures, warnings = [], []
    for name, text in texts.items():
        missing, misplaced = content_problems(expected, text)
        failures += [f"[{name}] missing {item}" for item in missing]
        target = failures if name in REQUIRED_EXTRACTORS else warnings
        target += [f"[{name}] out of order {item}" for item in misplaced]
    results = [_result("Content and order", failures)]
    if "pdftotext" in texts:
        results.append(_result("Column-guessing parsers", warnings, "warn"))
    return results


def glyph_problems(text: str) -> list[str]:
    problems = [f"ligature glyph {ch!r}" for ch in sorted(set(text) & set(_LIGATURES))]
    if "�" in text:
        problems.append("replacement character � (a glyph with no text mapping)")
    private = sorted({ch for ch in text if "" <= ch <= "" or ch >= "\U000f0000"})
    problems += [f"private-use character U+{ord(ch):04X}" for ch in private]
    for match in _BROKEN_WORD_RE.finditer(text):
        line = text[: match.end()].splitlines()[-2].strip()
        problems.append(f"word broken by a hyphen at a line end: {line[-40:]!r}")
    return problems


def heading_problems(headings: list[str] | None, text: str) -> list[str]:
    """Non-standard headings (extra sections) are flagged; without a YAML, look for the basics."""
    if headings is not None:
        return [f"non-standard heading: {h!r}" for h in headings if h not in STANDARD_HEADINGS]
    lines = {normalize(line) for line in text.splitlines()}
    return [
        f"no {h!r} heading found" for h in ("Experience", "Education") if h.lower() not in lines
    ]


def _embedded(font: Any) -> bool:
    font = font.get_object()
    if "/DescendantFonts" in font:
        return all(_embedded(child) for child in font["/DescendantFonts"])
    if font.get("/Subtype") == "/Type3":
        return True
    descriptor = font.get("/FontDescriptor", {})
    return any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))


def hygiene_problems(pdf: Path, config: Config) -> list[str]:
    reader = PdfReader(pdf)
    problems = []
    width, height = PAGE_SIZES[config.paper]
    for number, page in enumerate(reader.pages, start=1):
        if not page.extract_text().strip():
            problems.append(f"page {number} has no text layer")
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        problems += [
            f"page {number}: font {font.get_object().get('/BaseFont')} is not embedded"
            for font in fonts.values()
            if not _embedded(font)
        ]
        box = page.mediabox
        if abs(box.width - width) > 1 or abs(box.height - height) > 1:
            problems.append(
                f"page {number} is {box.width:.0f}x{box.height:.0f}pt, expected {config.paper}"
            )
    if len(reader.pages) > config.pages:
        problems.append(f"{len(reader.pages)} pages, limit is {config.pages}")
    size_mb = pdf.stat().st_size / 1_000_000
    if size_mb > config.max_file_mb:
        problems.append(f"file is {size_mb:.2f} MB, limit is {config.max_file_mb} MB")
    return problems


def jd_coverage(jd: str, text: str) -> CheckResult:
    """Informational only: which tech-looking JD keywords the resume text contains."""
    hay = normalize(text)
    # ponytail: tech-shaped tokens plus mid-sentence Capitalized words (Snowflake, Terraform);
    # lowercase tools like "dbt" need the keyword dictionary that arrives with verify.
    keywords = list(dict.fromkeys(tech_tokens(jd) + _PROPER_RE.findall(jd)))
    found = [k for k in keywords if k.lower() in hay]
    missing = [k for k in keywords if k.lower() not in hay]
    return CheckResult(
        f"JD keywords ({len(found)}/{len(keywords)} found)",
        "info",
        [f"found: {', '.join(found) or '-'}", f"missing: {', '.join(missing) or '-'}"],
    )


def run_checks(
    pdf: Path, config: Config, resume: Resume | None = None, jd: str | None = None
) -> tuple[list[CheckResult], dict[str, str]]:
    """Run every check. Name and content checks need the resume the PDF was rendered from."""
    texts = extract_all(pdf)
    view = build_view(resume, config) if resume else None
    headings = [section["heading"] for section in view["sections"]] if view else None
    results = []
    if resume and view:
        results.append(
            _result("Name", _each(texts, lambda t: name_problems(resume.basics.name, t)))
        )
    contact = _each(texts, lambda t: contact_problems(resume, t))
    results.append(
        _result("Contact", contact + (link_target_problems(resume, pdf) if resume else []))
    )
    if view:
        results += _content_results(flatten(view), texts)
    results.append(_result("Glyphs", _each(texts, glyph_problems)))
    primary = next(iter(texts.values()))
    results.append(_result("Headings", heading_problems(headings, primary), "warn"))
    results.append(_result("PDF hygiene", hygiene_problems(pdf, config)))
    if jd:
        results.append(jd_coverage(jd, primary))
    return results, texts
