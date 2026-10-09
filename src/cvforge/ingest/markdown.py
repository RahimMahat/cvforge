"""Markdown -> SourceDoc.

Besides headings, bullets and paragraphs, it understands the entry convention cvforge's own
Markdown output uses:

    **Company** | Location          a bold line starts an entry
    *Title* | Jun 2023 – Present    an italic line is its title (or a project's stack)
"""

import re

from cvforge.config import Config
from cvforge.dates import parse_date_range
from cvforge.ingest.sourcedoc import Block, SourceDoc
from cvforge.ingest.text import contact_blocks, is_headline, looks_like_contact

_HEADING_RE = re.compile(r"(#{1,6})\s+(.*?)\s*#*")
_BULLET_RE = re.compile(r"[-*+]\s+(.*)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_LINE_RE = re.compile(r"\*\*(.+?)\*\*((?: \| .+)?)")
_ITALIC_LINE_RE = re.compile(r"[*_]([^*_].*?)[*_]((?: \| .+)?)")
_LABELED_RE = re.compile(r"\*\*(.+?):\*\*\s+(.+)")  # **Languages:** Python, SQL


class _Parser:
    def __init__(self) -> None:
        self.doc = SourceDoc()

    def inline(self, text: str) -> tuple[str, str | None]:
        """Replace [text](url) with its text; returns the text and the first link target."""
        urls = []

        def link(match: re.Match[str]) -> str:
            shown = match.group(1).replace("**", "")
            self.doc.links.append({"text": shown, "url": match.group(2)})
            urls.append(match.group(2))
            return match.group(1)

        return _LINK_RE.sub(link, text), (urls[0] if urls else None)

    def add(self, kind: str, text: str, **fields: object) -> None:
        text, url = self.inline(" ".join(text.split()))
        if text:
            self.doc.blocks.append(Block(kind, text, url=url, **fields))  # type: ignore[arg-type]

    def entry_line(self, left: str, right: str, role: str) -> None:
        self.add("line", left, role=role, new_entry=role == "org")
        for part in filter(None, (p.strip() for p in right.split(" | "))):
            self.add("line", part, role="dates" if parse_date_range(part) else "location")


def parse_markdown(source: str, config: Config) -> SourceDoc:
    parser = _Parser()
    doc = parser.doc
    paragraph: list[str] = []
    seen_name = seen_section = False
    section: str | None = None

    def flush() -> None:
        if paragraph:
            text = " ".join(paragraph)
            if not seen_section and is_headline(text, doc):
                parser.add("line", text, role="headline")
            else:
                parser.add("paragraph", text)
            paragraph.clear()

    for raw in source.splitlines():
        line = raw.strip()
        hard_break = raw.endswith("  ")
        if not line:
            flush()
        elif heading := _HEADING_RE.fullmatch(line):
            flush()
            level = len(heading.group(1))
            if level == 1 and not seen_name:
                seen_name = True
                parser.add("line", heading.group(2), role="name")
            else:
                seen_section = True
                section = config.section_for(heading.group(2))
                parser.add("heading", heading.group(2), level=level)
        elif bullet := _BULLET_RE.fullmatch(line):
            flush()
            parser.add("bullet", bullet.group(1))
        elif not seen_section and looks_like_contact(_LINK_RE.sub(r"\1", line)):
            flush()
            for item in line.split(" | "):
                text, url = parser.inline(item.strip())
                if url:
                    doc.blocks.append(Block("line", text, role="contact", url=url))
                else:
                    doc.blocks += contact_blocks(text, doc)
        elif section == "skills" and (labeled := _LABELED_RE.fullmatch(line)):
            flush()
            parser.add("line", f"{labeled.group(1)}:", role="category")
            parser.add("line", labeled.group(2), role="skill")
        elif seen_section and (bold := _BOLD_LINE_RE.fullmatch(line)):
            flush()
            parser.entry_line(bold.group(1), bold.group(2), "org")
        elif seen_section and (italic := _ITALIC_LINE_RE.fullmatch(line)):
            flush()
            parser.entry_line(italic.group(1), italic.group(2), "title")
        else:
            paragraph.append(line)
            if hard_break:  # two trailing spaces end the line in Markdown
                flush()
    flush()
    return doc
