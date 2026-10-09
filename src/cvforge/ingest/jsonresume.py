"""JSON Resume (jsonresume.org) -> SourceDoc. Its fields are already labelled, so each one
becomes a block with a role and the rules extractor does the rest."""

import json
from typing import Any

from cvforge.config import Config
from cvforge.ingest.sourcedoc import Block, SourceDoc

# JSON Resume section -> (heading it becomes, {role: the key that holds it})
_SECTIONS = {
    "work": ("Experience", {"org": "name", "title": "position", "location": "location"}),
    "education": ("Education", {"org": "institution", "title": "studyType", "field": "area"}),
    "projects": ("Projects", {"title": "name", "description": "description"}),
    "certificates": ("Certifications", {"title": "name", "org": "issuer"}),
    "awards": ("Awards", {"title": "title", "org": "awarder"}),
    "publications": ("Publications", {"title": "name", "org": "publisher"}),
    "languages": ("Languages", {"title": "language", "description": "fluency"}),
}
_HANDLED = {"basics", "skills", "meta", "$schema", *_SECTIONS}


def _dates(item: dict[str, Any]) -> str:
    start = item.get("startDate")
    if start:  # JSON Resume leaves endDate out for a current position
        return f"{start} - {item.get('endDate') or 'present'}"
    return item.get("endDate") or item.get("date") or item.get("releaseDate") or ""


def _plain(value: Any) -> str:
    """Any leftover JSON value as readable text, so nothing is silently dropped."""
    if isinstance(value, dict):
        return ", ".join(filter(None, (_plain(v) for v in value.values())))
    if isinstance(value, list):
        return ", ".join(filter(None, (_plain(v) for v in value)))
    return str(value) if value not in (None, "") else ""


def parse_jsonresume(source: str, config: Config) -> SourceDoc:
    data = json.loads(source)
    if not isinstance(data, dict):
        raise ValueError("not a JSON Resume: the file must hold one JSON object")
    try:
        return _to_doc(data)
    except (AttributeError, TypeError, KeyError) as exc:  # e.g. "skills" holding plain strings
        raise ValueError(f"not a JSON Resume: unexpected structure ({exc})") from exc


def _to_doc(data: dict[str, Any]) -> SourceDoc:
    doc = SourceDoc()

    def add(kind: str, text: Any, **fields: Any) -> None:
        if text := " ".join(str(text or "").split()):
            doc.blocks.append(Block(kind, text, **fields))
            if fields.get("url"):
                doc.links.append({"text": text, "url": fields["url"]})

    basics = data.get("basics")
    basics = basics if isinstance(basics, dict) else {}
    add("line", basics.get("name"), role="name")
    add("line", basics.get("label"), role="headline")
    add("line", basics.get("email"), role="email")
    add("line", basics.get("phone"), role="phone")
    add("line", _plain(basics.get("location")), role="address")
    if basics.get("url"):
        add("line", basics["url"], role="contact", url=basics["url"])
    for profile in basics.get("profiles", []):
        if profile.get("url"):
            add(
                "line", profile.get("network") or profile["url"], role="contact", url=profile["url"]
            )
    if basics.get("summary"):
        add("heading", "Summary", level=2)
        add("paragraph", basics["summary"])

    if data.get("skills"):
        add("heading", "Skills", level=2)
        for skill in data["skills"]:
            add("line", skill.get("name"), role="category")
            add("line", ", ".join(skill.get("keywords", [])), role="skill")

    for key, (heading, roles) in _SECTIONS.items():
        if not data.get(key):
            continue
        add("heading", heading, level=2)
        for item in data[key] if isinstance(data[key], list) else [data[key]]:
            first = len(doc.blocks)
            if not isinstance(item, dict):  # not the documented shape: keep its text anyway
                add("bullet", _plain(item))
                continue
            for role, field in roles.items():
                add(
                    "line",
                    item.get(field),
                    role=role,
                    url=item.get("url") if role == "title" else None,
                )
            add("line", _dates(item), role="dates")
            add("line", ", ".join(item.get("keywords", [])), role="tech")
            add("line", item.get("score"), role="details")
            for course in item.get("courses", []):
                add("line", course, role="details")
            if key != "projects":  # a project's description already has a field
                add("paragraph", item.get("summary"))
            for highlight in item.get("highlights", []):
                add("bullet", highlight)
            if len(doc.blocks) > first:
                doc.blocks[first].new_entry = True

    for key, value in data.items():  # volunteer, interests, references, ...
        if key not in _HANDLED and value:
            add("heading", key.replace("_", " ").title(), level=2)
            for item in value if isinstance(value, list) else [value]:
                add("bullet", _plain(item))
    return doc
