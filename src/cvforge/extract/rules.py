"""Deterministic SourceDoc -> Resume mapping. Text is copied, never rewritten.

Anything the rules cannot place is kept verbatim in an extra section and reported.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from cvforge.config import Config
from cvforge.dates import parse_date_range
from cvforge.ingest.sourcedoc import Block, SourceDoc
from cvforge.models import Meta, Resume
from cvforge.render.view import display_url

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,16}\d")
_URLISH_RE = re.compile(r"\S+\.\S+")
_LEADING_BOLD_RE = re.compile(r"\*\*(.+?)\*\*\s*(.*)", re.S)
_ITEM_SEP_RE = re.compile(r",\s*(?![^()]*\))")  # commas, but not inside (parentheses)


def _split_items(text: str) -> list[str]:
    return [item.strip() for item in _ITEM_SEP_RE.split(text) if item.strip()]


# role -> field, per section. Entries missing a required field fall back to an extra section.
_FIELDS = {
    "experience": {"org": "company", "title": "title", "location": "location"},
    "projects": {"title": "name", "org": "name", "description": "description"},
    "education": {
        "org": "institution",
        "title": "degree",
        "field": "field",
        "location": "location",
    },
    "certifications": {"title": "name", "org": "issuer"},
    "awards": {"title": "title", "org": "awarder"},
    "publications": {"title": "name", "org": "publisher"},
    "languages": {"title": "language", "description": "fluency"},
}
_REQUIRED = {
    "experience": ("company", "title"),
    "projects": ("name",),
    "education": ("institution",),
    "certifications": ("name",),
    "awards": ("title",),
    "publications": ("name",),
    "languages": ("language",),
}


@dataclass
class Extraction:
    resume: Resume
    unplaced: list[str] = field(default_factory=list)  # "Heading: text" the rules could not map


class _Builder:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.data: dict[str, Any] = {"basics": {"links": []}, "skills": [], "extra_sections": []}
        self.unplaced: list[str] = []
        self.section: str | None = None  # schema key, "extra", or None before the first heading
        self.heading = ""
        self.anchor: str | None = None  # the last standard section seen, for placing extras
        self.entry: dict[str, Any] | None = None
        self.entry_section = ""
        self.category: str | None = None

    # --- sections that are not entries -------------------------------------------------

    def extra(self, text: str, title: str | None = None) -> None:
        title = title or self.heading or "Other"
        sections = self.data["extra_sections"]
        found = next((s for s in sections if s["title"] == title), None)
        if not found:
            found = {"title": title, "after": self.anchor, "items": []}
            sections.append(found)
        found["items"].append(text)

    def unplace(self, text: str) -> None:
        """Keep text the rules cannot map: verbatim, under its source heading, and reported."""
        self.unplaced.append(f"{self.heading or 'before the first heading'}: {text}")
        self.extra(text)

    def contact(self, block: Block) -> None:
        basics, text, url = self.data["basics"], block.text, block.url or ""
        if block.role in ("email", "phone", "headline"):
            basics[block.role] = text
        elif block.role == "address":
            basics["location"] = text
        elif url.startswith("mailto:") or (not url and _EMAIL_RE.fullmatch(text)):
            basics["email"] = text
        elif url.startswith("tel:") or (not url and _PHONE_RE.fullmatch(text)):
            basics["phone"] = text
        elif url:
            urlish = bool(_URLISH_RE.fullmatch(text))
            link = {"url": url, "label": None if urlish else text}
            if urlish and text != display_url(url):
                link["text"] = text  # the source showed something shorter than the target
            basics["links"].append(link)
        elif "location" not in basics:
            basics["location"] = text
        else:
            self.unplace(text)

    def skill_line(self, block: Block) -> None:
        if block.role == "category":
            self.category = block.text.rstrip(": ")
            return
        category, text = self.category, block.text
        if category is None and block.role != "skill" and ": " in text:
            category, text = text.split(": ", 1)
        self.category = None
        if category is None:
            self.unplace(block.text)
        else:
            self.data["skills"].append({"category": category, "items": _split_items(text)})

    # --- entries ----------------------------------------------------------------------

    def close_entry(self) -> None:
        entry, section = self.entry, self.entry_section
        self.entry = None
        if entry is None:
            return
        texts = entry.pop("_texts")
        if all(entry.get(name) for name in _REQUIRED[section]):
            self.data.setdefault(section, []).append(entry)
        else:  # not enough to form an entry: keep every piece verbatim instead
            for text in texts:
                self.unplace(text)

    def open_entry(self, section: str) -> dict[str, Any]:
        self.close_entry()
        self.entry, self.entry_section = {"_texts": []}, section
        return self.entry

    def dates(self, entry: dict[str, Any], section: str, text: str) -> bool:
        """Store a date line on the entry; False if it is not a date or has nowhere to go."""
        parsed = parse_date_range(text)
        if parsed is None or section == "projects":  # the schema has no project dates
            return False
        start, end = parsed
        if section not in ("experience", "education"):
            entry["date"] = end or start
        elif end is None and section == "education":
            entry["end"] = start  # a lone year on a degree is when it finished
        else:
            entry.update({key: value for key, value in (("start", start), ("end", end)) if value})
        return True

    def entry_block(self, block: Block, section: str) -> None:
        text, role = block.text, block.role
        if block.new_entry:
            self.open_entry(section)
        entry = self.entry if self.entry_section == section else None
        if entry is None:
            if section == "projects" and (match := _LEADING_BOLD_RE.fullmatch(text)):
                # "**Name** rest of the bullet": the bold lead is the project's name
                entry = self.open_entry(section)
                entry["_texts"].append(text)
                entry["name"] = match.group(1)
                if match.group(2):
                    entry["description"] = match.group(2)
                if block.url:
                    entry["url"] = block.url
                self.close_entry()
            else:
                self.unplace(text)
            return
        if section == "experience" and role == "title" and entry.get("title"):
            # a second title under one company line is another role at that company
            company = entry["company"]
            entry = self.open_entry(section)
            entry["company"] = company
        entry["_texts"].append(text)
        fields = _FIELDS[section]
        if role in fields and fields[role] not in entry:
            entry[fields[role]] = text
            if section in ("projects", "publications") and block.url:
                entry["url"] = block.url
        elif section == "projects" and role == "title" and "tech" not in entry:
            entry["tech"] = _split_items(text)  # the line under a project's name is its stack
        elif role == "dates" and self.dates(entry, section, text):
            pass
        elif role == "tech" and section == "projects":
            entry["tech"] = _split_items(text)
        elif block.kind == "bullet" and section in ("experience", "projects"):
            entry.setdefault("bullets", []).append(text)
        elif section == "projects" and role is None and "description" not in entry:
            entry["description"] = text  # an unlabelled paragraph under a project describes it
        elif section == "education" and role in (None, "details", "description"):
            entry.setdefault("details", []).append(text)
        else:
            entry["_texts"].pop()
            self.unplace(text)

    # --- driver -----------------------------------------------------------------------

    def add(self, block: Block) -> None:
        if block.role == "name":
            self.data["basics"]["name"] = block.text
        elif block.role in ("contact", "email", "phone", "address", "headline"):
            self.contact(block)
        elif block.kind == "heading":
            self.close_entry()
            self.heading = block.text
            self.section = self.config.section_for(block.text) or "extra"
            if self.section != "extra":
                self.anchor = self.section
            self.category = None
        else:
            section = block.section or self.section
            if block.section:
                self.anchor = block.section
            if section in _FIELDS:
                self.entry_block(block, section)
            elif section in (None, "summary"):
                if "summary" not in self.data and block.kind != "bullet":
                    self.data["summary"] = block.text
                    self.anchor = "summary"
                else:
                    self.unplace(block.text)
            elif section == "skills":
                self.skill_line(block)
            elif section == "extra":
                self.extra(block.text)
            else:  # e.g. languages written as one sentence
                self.unplace(block.text)


def source_headings(doc: SourceDoc, config: Config) -> dict[str, str]:
    """Standard section -> the heading the source used for it, e.g. experience: Work Experience.

    A heading the synonyms do not know still counts when the template marks the entries
    under it, as with a "Technical Contributions" section made of project entries.
    """
    found: dict[str, str] = {}
    pending = ""
    for block in doc.blocks:
        if block.kind == "heading":
            pending = block.text
            if key := config.section_for(pending):
                found.setdefault(key, pending)
                pending = ""
        elif pending and block.section:
            found.setdefault(block.section, pending)
            pending = ""
    return found


def extract(doc: SourceDoc, config: Config, meta: Meta) -> Extraction:
    builder = _Builder(config)
    for block in doc.blocks:
        builder.add(block)
    builder.close_entry()
    resume = Resume.model_validate({**builder.data, "meta": meta.model_dump()})
    return Extraction(resume, builder.unplaced)
