"""Plain text -> SourceDoc. Text has no markup, so only the obvious structure is recovered:
the name, the contact line, headings, bullets and paragraphs. Entries stay as plain lines."""

import re

from cvforge.config import Config
from cvforge.ingest.sourcedoc import Block, SourceDoc

_BULLET_RE = re.compile(r"[-•*·▪◦‣]\s+(.*)")
_URLISH_RE = re.compile(r"(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?")
_CONTACT_SPLIT_RE = re.compile(r"\s+[|•·]\s+")


def contact_blocks(line: str, doc: SourceDoc) -> list[Block]:
    """Split 'email | phone | site' into contact blocks, giving bare web addresses a URL."""
    blocks = []
    for item in filter(None, (part.strip() for part in _CONTACT_SPLIT_RE.split(line))):
        url = None
        if "@" not in item and _URLISH_RE.fullmatch(item):
            url = item if item.startswith("http") else f"https://{item}"
            doc.links.append({"text": item, "url": url})
        blocks.append(Block("line", item, role="contact", url=url))
    return blocks


def looks_like_contact(line: str) -> bool:
    return "@" in line or bool(_CONTACT_SPLIT_RE.search(line))


def is_headline(line: str, doc: SourceDoc) -> bool:
    """A short line directly under the name, such as 'Senior Data Engineer'."""
    under_name = bool(doc.blocks) and doc.blocks[-1].role == "name"
    return under_name and len(line) <= 80 and not line.endswith(".")


def _is_heading(line: str, config: Config) -> bool:
    text = line.rstrip(":")
    shouting = text.isupper() and len(text.split()) <= 4 and not re.search(r"[\d@|,.]", text)
    return config.section_for(text) is not None or shouting


def parse_text(source: str, config: Config) -> SourceDoc:
    doc = SourceDoc()
    seen_heading = False
    after_blank = True
    for raw in source.splitlines():
        line = " ".join(raw.split())
        if not line:
            after_blank = True
            continue
        previous = doc.blocks[-1] if doc.blocks else None
        if previous is None:
            doc.blocks.append(Block("line", line, role="name"))
        elif _is_heading(line, config):
            seen_heading = True
            doc.blocks.append(Block("heading", line.rstrip(":"), level=2))
        elif bullet := _BULLET_RE.fullmatch(line):
            doc.blocks.append(Block("bullet", bullet.group(1)))
        elif not seen_heading and looks_like_contact(line):
            doc.blocks += contact_blocks(line, doc)
        elif not seen_heading and is_headline(line, doc):
            doc.blocks.append(Block("line", line, role="headline"))
        elif (
            # ponytail: a lowercase start right after a bullet or paragraph is treated as a
            # wrapped line (PDF text is hard-wrapped); real layout analysis would do better.
            not after_blank
            and line[0].islower()
            and previous.kind in ("bullet", "paragraph")
            and previous.role is None
        ):
            previous.text = f"{previous.text} {line}"
        else:
            doc.blocks.append(Block("paragraph", line))
        after_blank = False
    return doc
