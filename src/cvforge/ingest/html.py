"""HTML resume -> SourceDoc. Class names from config say what each element is."""

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import PreformattedString

from cvforge.config import Config
from cvforge.ingest.sourcedoc import Block, SourceDoc

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_INLINE = {"a", "b", "strong", "em", "i", "u", "span", "small", "code", "sup", "sub", "br"}
_BOLD = {"b", "strong"}


class _Walker:
    def __init__(self, config: Config) -> None:
        self.classes = config.html_classes
        self.doc = SourceDoc()
        self.entry_section: str | None = None  # section of the entry wrapper being walked
        self.entry_started = False
        self.seen_name = False

    def role(self, tag: Tag) -> str | None:
        return next((self.classes[c] for c in tag.get("class") or [] if c in self.classes), None)

    def is_inline(self, tag: Tag) -> bool:
        """Inline unless the config gives it (or anything inside it) a role."""
        if tag.name not in _INLINE or self.role(tag):
            return False
        return not any(self.role(child) for child in tag.find_all(True))

    def inline(self, node: Tag | NavigableString) -> str:
        """Text with <strong>/<b> as **bold**; link targets are recorded."""
        if isinstance(node, NavigableString):
            return str(node)
        if node.name == "br":
            return " "
        text = "".join(self.inline(child) for child in node.children)
        if node.name == "a" and node.get("href") and text.strip():
            self.doc.links.append({"text": " ".join(text.split()), "url": str(node["href"])})
        if node.name in _BOLD and text.strip() and "**" not in text:
            return f"**{text.strip()}**"
        return text

    def emit(self, kind: str, text: str, role: str | None = None, level: int = 0, url=None) -> None:
        text = " ".join(text.split())
        if not text:
            return
        block = Block(kind, text, level, role, url)  # type: ignore[arg-type]
        if self.entry_section and kind != "heading":
            block.section, block.new_entry = self.entry_section, not self.entry_started
            self.entry_started = True
        self.doc.blocks.append(block)

    def walk(self, tag: Tag, role: str | None = None, kind: str = "paragraph") -> None:
        """Emit the tag's own text as blocks of `kind`, descending into block-level children."""
        buffer: list[str] = []
        first_link = len(self.doc.links)

        def flush() -> None:
            links = self.doc.links[first_link:] if buffer else []
            self.emit(kind, "".join(buffer), role, url=links[0]["url"] if links else None)
            buffer.clear()

        for child in tag.children:
            if isinstance(child, PreformattedString):  # comments, CDATA, doctype
                continue
            if isinstance(child, NavigableString) or self.is_inline(child):
                if not buffer:
                    first_link = len(self.doc.links)
                buffer.append(self.inline(child))
            elif isinstance(child, Tag):
                flush()
                self.block(child)
        flush()

    def block(self, tag: Tag) -> None:
        role = self.role(tag)
        if role == "skip" or tag.get("hidden") is not None:
            return
        if "display:none" in str(tag.get("style", "")).replace(" ", ""):
            return
        if role and role.startswith("entry:"):
            self.entry_section, self.entry_started = role.removeprefix("entry:"), False
            self.walk(tag)
            self.entry_section = None
        elif role == "contact":
            for child in tag.find_all(True, recursive=False):
                if self.role(child) != "skip":
                    href = str(child.get("href")) if child.get("href") else None
                    self.emit("line", self.inline(child), "contact", url=href)
        elif role == "heading" or tag.name in _HEADINGS:
            if tag.name == "h1" and not self.seen_name:
                self.seen_name = True
                self.emit("line", self.inline(tag), "name")
            else:
                self.emit("heading", self.inline(tag), level=_HEADINGS.get(tag.name, 2))
        elif tag.name == "li":
            self.walk(tag, role, "bullet")
        elif role:
            self.walk(tag, role, "bullet" if role == "item" else "line")
        else:
            self.walk(tag)


def parse_html(source: str, config: Config) -> SourceDoc:
    soup = BeautifulSoup(source, "lxml")
    for tag in soup(["script", "style", "head", "template", "noscript"]):
        tag.decompose()
    walker = _Walker(config)
    if soup.body:
        walker.walk(soup.body)
    return walker.doc
