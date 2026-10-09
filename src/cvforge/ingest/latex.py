"""LaTeX resume -> SourceDoc. The source is parsed, never compiled.

The macro map in config says which macros carry resume fields, so a new template is
supported by editing cvforge.toml rather than this file.
"""

import re
from typing import Any

from pylatexenc.latex2text import LatexNodes2Text
from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexCommentNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexSpecialsNode,
    LatexWalker,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import MacroSpec

from cvforge.config import Config
from cvforge.ingest.sourcedoc import Block, SourceDoc

_SECTIONS = {"section": 1, "subsection": 2, "subsubsection": 3}
_ESCAPES = set("%&_#${}")
_SPECIALS = {"~": " ", "--": "–", "---": "—", "``": "“", "''": "”"}
_BOLD = {"textbf", "bfseries"}
_PASSTHROUGH = {"textit", "emph", "underline", "textsc", "texttt", "textsf", "textrm", "mbox"}
_ENTRY_ROLES = {"org", "title"}
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")


def _children(node: Any) -> list[Any]:
    """The nodes inside a {group}; a bare node stands for itself."""
    return node.nodelist if node.isNodeType(LatexGroupNode) else [node]


class _Walker:
    def __init__(self, config: Config) -> None:
        self.macros = config.latex_macros
        self.doc = SourceDoc()
        self.to_text = LatexNodes2Text()
        specs = [MacroSpec(name, "[" + "{" * len(roles)) for name, roles in self.macros.items()]
        self.context = get_default_latex_context_db()
        self.context.add_context_category(
            "cvforge", prepend=True, macros=[*specs, MacroSpec("href", "{{")]
        )

    def parse(self, source: str) -> list[Any]:
        return LatexWalker(source, latex_context=self.context).get_latex_nodes()[0]

    def args(self, node: LatexMacroNode) -> list[Any]:
        return [arg for arg in (node.nodeargd.argnlist if node.nodeargd else []) if arg]

    def roles(self, node: Any) -> list[str]:
        """Argument roles if the node is a macro from the config map with any role set."""
        if node is None or not node.isNodeType(LatexMacroNode):
            return []
        roles = self.macros.get(node.macroname, [])
        return roles if any(roles) else []

    def structural(self, nodes: list[Any]) -> bool:
        """True if the nodes hold a section, a list or a field macro rather than plain text."""
        for node in nodes:
            if node is None:
                continue
            if node.isNodeType(LatexEnvironmentNode) or self.roles(node):
                return True
            if node.isNodeType(LatexMacroNode) and node.macroname in _SECTIONS:
                return True
            if node.isNodeType(LatexGroupNode) and self.structural(node.nodelist):
                return True
        return False

    def inline(self, nodes: list[Any]) -> str:
        """Plain text with \\textbf as **bold**; link targets are recorded."""
        out: list[str] = []
        for node in nodes:
            if node is None or isinstance(node, str):
                out.append(node or "")
            elif node.isNodeType(LatexCharsNode):
                out.append(node.chars)
            elif node.isNodeType(LatexCommentNode):
                continue
            elif node.isNodeType(LatexSpecialsNode):
                out.append(_SPECIALS.get(node.specials_chars, node.specials_chars))
            elif node.isNodeType(LatexGroupNode) or node.isNodeType(LatexEnvironmentNode):
                out.append(self.inline(node.nodelist))
            elif node.isNodeType(LatexMacroNode):
                out.append(self.macro(node))
        return "".join(out)

    def macro(self, node: LatexMacroNode) -> str:
        name, args = node.macroname, self.args(node)
        if name in _ESCAPES:
            return name
        if name in self.macros:  # spacing and field macros never contribute inline text
            return ""
        if name == "href" and len(args) == 2:
            url = self.inline(_children(args[0])).strip()
            text = self.inline(_children(args[1]))
            self.doc.links.append({"text": " ".join(text.replace("**", "").split()), "url": url})
            return text
        if name == "url" and args:
            url = self.inline(_children(args[0])).strip()
            self.doc.links.append({"text": url, "url": url})
            return url
        if name in _BOLD | _PASSTHROUGH:
            text = self.inline([child for arg in args for child in _children(arg)])
            bold = name in _BOLD and text.strip() and "**" not in text
            return f"**{text.strip()}**" if bold else text
        return self.to_text.nodelist_to_text([node])

    def emit(self, kind: str, text: str, **fields: Any) -> Block | None:
        text = " ".join(text.split())
        if not text:
            return None
        block = Block(kind, text, **fields)  # type: ignore[arg-type]
        self.doc.blocks.append(block)
        return block

    def paragraph(self, nodes: list[Any], kind: str = "paragraph") -> None:
        first_link = len(self.doc.links)
        text = self.inline(nodes)
        links = self.doc.links[first_link:]
        self.emit(kind, text, url=links[0]["url"] if links else None)

    def fields(self, node: LatexMacroNode) -> None:
        """Emit one block per mapped argument of a field macro such as \\cventry or \\email."""
        roles = self.roles(node)
        is_entry = bool(_ENTRY_ROLES & set(roles))
        name_parts, first = [], True
        # argnlist[0] is the optional [argument] slot every mapped macro is parsed with
        for role, arg in zip(roles, node.nodeargd.argnlist[1:], strict=False):
            if arg is None:
                continue
            nodes = _children(arg)
            if role == "body":
                self.walk(nodes)
            elif role == "name":
                name_parts.append(self.inline(nodes).strip())
            elif role == "links":
                first_link = len(self.doc.links)
                self.inline(nodes)
                for link in self.doc.links[first_link:]:
                    self.emit("line", link["text"], role="contact", url=link["url"])
            elif role:
                if not is_entry and role == "location":
                    role = "address"
                block = self.emit("line", self.inline(nodes), role=role)
                if block and is_entry and first:
                    block.new_entry, first = True, False
        if name_parts:
            self.emit("line", " ".join(name_parts), role="name")

    def items(self, nodes: list[Any]) -> None:
        """A list environment: each \\item is a bullet, unless it wraps an entry."""
        chunks: list[list[Any]] = []
        for node in nodes:
            if node.isNodeType(LatexMacroNode) and node.macroname == "item":
                chunks.append([])
            elif chunks:
                chunks[-1].append(node)
        for chunk in chunks:
            if self.structural(chunk):
                self.walk(chunk)
            else:
                self.paragraph(chunk, "bullet")

    def walk(self, nodes: list[Any]) -> None:
        buffer: list[Any] = []

        def flush() -> None:
            self.paragraph(buffer)
            buffer.clear()

        for node in nodes:
            if node is None:
                continue
            if node.isNodeType(LatexMacroNode) and node.macroname in _SECTIONS:
                flush()
                level = _SECTIONS[node.macroname]
                self.emit("heading", self.inline(self.args(node)[-1:]), level=level)
            elif self.roles(node):
                flush()
                self.fields(node)
            elif node.isNodeType(LatexEnvironmentNode):
                flush()
                is_list = any(
                    n.isNodeType(LatexMacroNode) and n.macroname == "item" for n in node.nodelist
                )
                self.items(node.nodelist) if is_list else self.walk(node.nodelist)
            elif node.isNodeType(LatexGroupNode) and self.structural(node.nodelist):
                flush()
                self.walk(node.nodelist)
            elif node.isNodeType(LatexCharsNode):
                first, *rest = _PARAGRAPH_BREAK.split(node.chars)
                buffer.append(first)
                for part in rest:  # a blank line ends the paragraph
                    flush()
                    buffer.append(part)
            else:
                buffer.append(node)
        flush()


def parse_latex(source: str, config: Config) -> SourceDoc:
    walker = _Walker(config)
    preamble, found, body = source.partition(r"\begin{document}")
    if not found:
        preamble, body = "", source
    for node in walker.parse(preamble):  # only field macros count before \begin{document}
        if walker.roles(node):
            walker.fields(node)
    walker.walk(walker.parse(body.split(r"\end{document}")[0]))
    return walker.doc
