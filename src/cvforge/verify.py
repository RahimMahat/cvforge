"""Faithfulness guard: prove a resume.yaml says what its source says, no more and no less.

Units of comparison:
  whole   bullets and extra-section items: each must match one source block as a whole
  prose   summary, descriptions, details: a whole block, or a verbatim run inside one
  parts   names, titles, companies, skill items, ...: must appear verbatim in the source
  dates   compared by value, since YYYY-MM is a normalization of the source's wording
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from cvforge.check.ats import CheckResult
from cvforge.config import Config
from cvforge.dates import DatePair, find_date_ranges
from cvforge.ingest.sourcedoc import SourceDoc
from cvforge.models import Resume
from cvforge.render.view import display_url
from cvforge.textnorm import normalize, tech_tokens

FUZZY_MIN = 95
_NUMBER_RE = re.compile(r"[₹$€£]?\d+(?:[.,]\d+)*(?:%|\+|[xkKML]\b)?")
_PUNCTUATION_RE = re.compile(r"[\W_]+")


@dataclass
class Units:
    whole: list[tuple[str, str]] = field(default_factory=list)  # (location, text)
    prose: list[tuple[str, str]] = field(default_factory=list)
    parts: list[tuple[str, str]] = field(default_factory=list)
    urls: list[tuple[str, str]] = field(default_factory=list)
    dates: list[tuple[str, DatePair]] = field(default_factory=list)
    groups: list[tuple[str, list[str]]] = field(default_factory=list)  # ordered bullet lists

    def texts(self) -> list[str]:
        return [text for _, text in self.whole + self.prose + self.parts]


def collect(resume: Resume) -> Units:
    """Every piece of content in the resume, tagged with where it lives."""
    u = Units()

    def parts(where: str, **values: str | None) -> None:
        u.parts += [(f"{where}.{key}", value) for key, value in values.items() if value]

    def group(where: str, items: list[str]) -> None:
        u.whole += [(f"{where}[{i}]", item) for i, item in enumerate(items)]
        u.groups.append((where, items))

    b = resume.basics
    parts("basics", name=b.name, headline=b.headline, email=b.email, phone=b.phone)
    parts("basics", location=b.location)
    for i, link in enumerate(b.links):
        parts(f"basics.links[{i}]", label=link.label, text=link.text)
        u.urls.append((f"basics.links[{i}].url", link.url))
    if resume.summary:
        u.prose.append(("summary", resume.summary))
    for i, skill in enumerate(resume.skills):
        parts(f"skills[{i}]", category=skill.category)
        u.parts += [(f"skills[{i}].items[{j}]", item) for j, item in enumerate(skill.items)]
    for i, job in enumerate(resume.experience):
        where = f"experience[{i}]"
        parts(where, company=job.company, title=job.title, location=job.location)
        u.dates.append((where, (job.start, job.end)))
        group(f"{where}.bullets", job.bullets)
    for i, project in enumerate(resume.projects):
        where = f"projects[{i}]"
        parts(where, name=project.name)
        u.parts += [(f"{where}.tech[{j}]", item) for j, item in enumerate(project.tech)]
        if project.url:
            u.urls.append((f"{where}.url", project.url))
        if project.description:
            u.prose.append((f"{where}.description", project.description))
        group(f"{where}.bullets", project.bullets)
    for i, edu in enumerate(resume.education):
        where = f"education[{i}]"
        parts(where, institution=edu.institution, degree=edu.degree, field=edu.field)
        parts(where, location=edu.location)
        u.dates.append((where, (edu.start, edu.end)))
        u.prose += [(f"{where}.details[{j}]", d) for j, d in enumerate(edu.details)]
    for i, cert in enumerate(resume.certifications):
        parts(f"certifications[{i}]", name=cert.name, issuer=cert.issuer)
        u.dates.append((f"certifications[{i}]", (cert.date, None)))
    for i, award in enumerate(resume.awards):
        parts(f"awards[{i}]", title=award.title, awarder=award.awarder)
        u.dates.append((f"awards[{i}]", (award.date, None)))
    for i, pub in enumerate(resume.publications):
        parts(f"publications[{i}]", name=pub.name, publisher=pub.publisher)
        u.dates.append((f"publications[{i}]", (pub.date, None)))
        if pub.url:
            u.urls.append((f"publications[{i}].url", pub.url))
    for i, lang in enumerate(resume.languages):
        parts(f"languages[{i}]", language=lang.language, fluency=lang.fluency)
    for i, extra in enumerate(resume.extra_sections):
        parts(f"extra_sections[{i}]", title=extra.title)
        group(f"extra_sections[{i}].items", extra.items)
    u.dates = [(where, pair) for where, pair in u.dates if any(pair)]
    return u


def _values(pair: DatePair) -> tuple[str, ...]:
    return tuple(value for value in pair if value)


def _best(text: str, choices: list[str]) -> tuple[float, int]:
    """(score, index) of the choice closest to text; (0, -1) if there are none."""
    found = process.extractOne(text, choices, scorer=fuzz.ratio)
    return (found[1], found[2]) if found else (0.0, -1)


def _residue(block: str, units: Units, dates: set[tuple[str, ...]]) -> str:
    """What is left of a source block once every date and field the resume holds is removed."""
    for pair, (start, end) in reversed(find_date_ranges(block)):
        if _values(pair) in dates:
            block = block[:start] + " " + block[end:]
    block = normalize(block)
    pieces = {normalize(text) for _, text in units.parts + units.prose}
    for _, url in units.urls:  # a link may be shown as its URL, with or without the scheme
        pieces |= {normalize(url), normalize(display_url(url))}
    for piece in sorted(pieces, key=len, reverse=True):
        if piece:
            block = block.replace(piece, " ")
    return _PUNCTUATION_RE.sub("", block)


def verify(doc: SourceDoc, resume: Resume, config: Config) -> list[CheckResult]:
    """Compare a resume against its (already drop-filtered) source. Any failure names the text."""
    units = collect(resume)
    blocks = [b for b in doc.blocks if b.kind != "heading"]  # headings are renamed, not content
    source = [normalize(b.text) for b in blocks]
    haystack = normalize(doc.raw_text)
    source_urls = {link["url"] for link in doc.links}
    whole = [normalize(text) for _, text in units.whole]
    yaml_dates = {_values(pair) for _, pair in units.dates}
    source_dates = {_values(pair) for b in blocks for pair, _ in find_date_ranges(b.text)}

    # Coverage: every source block is in the resume, whole or as the sum of its fields.
    uncovered = [
        f"{block.kind}: {block.text!r}"
        for block, text in zip(blocks, source, strict=True)
        if text and _best(text, whole)[0] < FUZZY_MIN and _residue(block.text, units, yaml_dates)
    ]

    # No additions: every piece of the resume is in the source.
    added = [
        f"{where}: {text!r}"
        for where, text in units.whole
        if _best(normalize(text), source)[0] < FUZZY_MIN
    ]
    added += [
        f"{where}: {text!r}"
        for where, text in units.prose
        if normalize(text) not in haystack and _best(normalize(text), source)[0] < FUZZY_MIN
    ]
    added += [
        f"{where}: {text!r}" for where, text in units.parts if normalize(text) not in haystack
    ]
    source_headings = {normalize(b.text) for b in doc.blocks if b.kind == "heading"}
    added += [
        f"meta.headings.{key}: {text!r}"
        for key, text in resume.meta.headings.items()
        if normalize(text) not in source_headings
    ]
    added += [
        f"{where}: {url!r}"
        for where, url in units.urls
        if url not in source_urls and display_url(url).lower() not in haystack
    ]
    added += [
        f"{where}: dates {' to '.join(_values(pair))} not in the source"
        for where, pair in units.dates
        if _values(pair) not in source_dates
    ]

    # Numbers: nothing numeric may appear that the source does not have.
    source_numbers = set(_NUMBER_RE.findall(doc.raw_text))
    numbers = sorted({n for text in units.texts() for n in _NUMBER_RE.findall(text)})
    new_numbers = [f"{n!r} is not in the source" for n in numbers if n not in source_numbers]

    # Keywords: no technology named in the source may go missing.
    resume_text = normalize(" ".join(units.texts() + [url for _, url in units.urls]))
    source_text = " ".join(b.text for b in blocks)
    dictionary = [k for k in config.keywords() if normalize(k) in haystack]
    keywords = dict.fromkeys(tech_tokens(source_text) + dictionary)
    lost = [f"{k!r} is missing" for k in keywords if normalize(k) not in resume_text]

    # Order: bullets keep the order they had in the source.
    reordered = []
    for where, items in units.groups:
        positions = [_best(normalize(item), source) for item in items]
        indexes = [index for score, index in positions if score >= FUZZY_MIN]
        if indexes != sorted(indexes):
            reordered.append(f"{where}: bullets are not in source order")

    return [
        CheckResult("Coverage", "fail" if uncovered else "pass", uncovered),
        CheckResult("No additions", "fail" if added else "pass", added),
        CheckResult("Numbers", "fail" if new_numbers else "pass", new_numbers),
        CheckResult("Keywords", "fail" if lost else "pass", lost),
        CheckResult("Order", "fail" if reordered else "pass", reordered),
    ]


def passed(results: list[CheckResult]) -> bool:
    return not any(result.status == "fail" for result in results)


def _sidecar(yaml_path: Path) -> Path:
    return yaml_path.with_name(yaml_path.name + ".verified")


def _digest(yaml_path: Path) -> str:
    return hashlib.sha256(yaml_path.read_bytes()).hexdigest()


def write_sidecar(yaml_path: Path, source: Path, results: list[CheckResult]) -> None:
    """Record the verification result against this exact YAML content."""
    record = {"source": source.as_posix(), "sha256": _digest(yaml_path), "passed": passed(results)}
    _sidecar(yaml_path).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def verification_state(yaml_path: Path) -> str:
    """'passed', 'edited' (passed, then the YAML changed), 'failed' or 'unverified'."""
    try:
        record = json.loads(_sidecar(yaml_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # never verified, or the record is unreadable
        return "unverified"
    if not isinstance(record, dict):
        return "unverified"
    if not record.get("passed"):
        return "failed"
    return "passed" if record.get("sha256") == _digest(yaml_path) else "edited"
