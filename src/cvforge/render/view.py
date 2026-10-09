"""Turn a Resume into the render view shared by every output format.

The view is plain data: a name, a contact line and sections of blocks. Block kinds:
  paragraph  {segments}
  labeled    {label, segments}            e.g. Languages: Python, SQL
  bullets    {items: [segments]}
  entry      {lines: [{left, right, style}], paragraphs, bullets, continued}
"""

import re
from collections.abc import Iterable
from datetime import date
from itertools import groupby
from typing import Any

from cvforge.config import Config
from cvforge.models import Education, Experience, Project, Resume
from cvforge.render.segments import Segment, to_segments

Block = dict[str, Any]

HEADINGS = {
    "summary": "Summary",
    "skills": "Skills",
    "experience": "Experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
    "awards": "Awards",
    "publications": "Publications",
    "languages": "Languages",
}


def format_date(value: str, fmt: str) -> str:
    if value == "present":
        return "Present"
    if "-" not in value:
        return value
    year, month = value.split("-")
    return date(int(year), int(month), 1).strftime(fmt)


def date_range(start: str | None, end: str | None, fmt: str) -> str:
    return " – ".join(format_date(d, fmt) for d in (start, end) if d)


def display_url(url: str) -> str:
    return re.sub(r"^[a-z]+://", "", url).rstrip("/")


def _line(left: list[Segment], right: str = "", style: str = "plain") -> dict[str, Any]:
    return {"left": left, "right": right, "style": style}


def _entry(
    lines: list[dict[str, Any]],
    paragraphs: Iterable[str] = (),
    bullets: Iterable[str] = (),
    continued: bool = False,
) -> Block:
    return {
        "kind": "entry",
        "lines": lines,
        "paragraphs": [to_segments(p) for p in paragraphs],
        "bullets": [to_segments(b) for b in bullets],
        "continued": continued,
    }


def _bullets(items: list[str]) -> Block:
    return {"kind": "bullets", "items": [to_segments(item) for item in items]}


def _dated(name: str, by: str | None, when: str | None, fmt: str) -> Block:
    """One line such as 'SnowPro Core, Snowflake' with the date on the right."""
    left = to_segments(name) + ([{"text": f", {by}", "bold": False}] if by else [])
    return _entry([_line(left, format_date(when, fmt) if when else "")], continued=True)


def _experience(jobs: list[Experience], fmt: str) -> list[Block]:
    """Consecutive roles at one company share a single company line."""
    blocks: list[Block] = []
    for company, group in groupby(jobs, key=lambda job: job.company):
        roles = list(group)
        shared = roles[0].location if len({role.location for role in roles}) == 1 else None
        for i, role in enumerate(roles):
            dates = date_range(role.start, role.end, fmt)
            where = None if shared else role.location
            right = " | ".join(x for x in (where, dates) if x)
            lines = [_line(to_segments(role.title), right, "secondary")]
            if i == 0:
                lines.insert(0, _line(to_segments(company), shared or "", "primary"))
            blocks.append(_entry(lines, bullets=role.bullets, continued=i > 0))
    return blocks


def _project(project: Project) -> Block:
    name = to_segments(project.name)
    if project.url:
        name = [{**segment, "url": project.url} for segment in name]
    lines = [_line(name, style="primary")]
    if project.tech:
        lines.append(_line(to_segments(", ".join(project.tech)), style="secondary"))
    paragraphs = [project.description] if project.description else []
    return _entry(lines, paragraphs, project.bullets)


def _education(edu: Education, fmt: str) -> Block:
    lines = [_line(to_segments(edu.institution), edu.location or "", "primary")]
    dates = date_range(edu.start, edu.end, fmt)
    degree = ", ".join(x for x in (edu.degree, edu.field) if x)
    if degree or dates:
        lines.append(_line(to_segments(degree), dates, "secondary"))
    return _entry(lines, edu.details)


def _blocks(resume: Resume, key: str, fmt: str) -> list[Block]:
    match key:
        case "summary":
            text = resume.summary
            return [{"kind": "paragraph", "segments": to_segments(text)}] if text else []
        case "skills":
            return [
                {
                    "kind": "labeled",
                    "label": g.category,
                    "segments": to_segments(", ".join(g.items)),
                }
                for g in resume.skills
            ]
        case "experience":
            return _experience(resume.experience, fmt)
        case "projects":
            return [_project(p) for p in resume.projects]
        case "education":
            return [_education(e, fmt) for e in resume.education]
        case "certifications":
            return [_dated(c.name, c.issuer, c.date, fmt) for c in resume.certifications]
        case "awards":
            return [_dated(a.title, a.awarder, a.date, fmt) for a in resume.awards]
        case "publications":
            return [_dated(p.name, p.publisher, p.date, fmt) for p in resume.publications]
        case "languages":
            return [
                {"kind": "labeled", "label": lang.language, "segments": to_segments(lang.fluency)}
                if lang.fluency
                else {"kind": "paragraph", "segments": to_segments(lang.language)}
                for lang in resume.languages
            ]
    raise ValueError(f"unknown section in section_order: {key!r}")


def _contact(resume: Resume) -> list[dict[str, str | None]]:
    basics = resume.basics
    items: list[dict[str, str | None]] = []
    if basics.email:
        items.append({"text": basics.email, "url": f"mailto:{basics.email}"})
    items += [{"text": text, "url": None} for text in (basics.phone, basics.location) if text]
    items += [{"text": ln.text or display_url(ln.url), "url": ln.url} for ln in basics.links]
    return items


def build_view(resume: Resume, config: Config) -> dict[str, Any]:
    sections = []
    for key in config.section_order:
        if key == "extra_sections":
            sections += [
                {"heading": extra.title, "blocks": [_bullets(extra.items)]}
                for extra in resume.extra_sections
                if extra.items
            ]
        elif blocks := _blocks(resume, key, config.date_format):
            sections.append({"heading": HEADINGS[key], "blocks": blocks})
    return {
        "name": resume.basics.name,
        "headline": resume.basics.headline,
        "contact": _contact(resume),
        "sections": sections,
    }
