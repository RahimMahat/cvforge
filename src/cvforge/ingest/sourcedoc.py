"""SourceDoc: a source resume reduced to ordered text blocks, before any schema mapping."""

from dataclasses import dataclass, field
from typing import Literal

from cvforge.config import Config
from cvforge.textnorm import normalize

Kind = Literal["heading", "paragraph", "bullet", "line"]


@dataclass
class Block:
    kind: Kind
    text: str  # inline markup already reduced to **bold**
    level: int = 0
    role: str | None = None  # what the source's template says this is: org, title, dates, ...
    url: str | None = None  # link target, when the block is (or starts with) a link
    new_entry: bool = False  # first block of a job, project, degree, ...
    section: str | None = None  # schema section the template assigns, overriding the heading


@dataclass
class SourceDoc:
    blocks: list[Block] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)  # {text, url}

    @property
    def raw_text(self) -> str:
        return "\n".join(block.text for block in self.blocks)


def split_dropped(doc: SourceDoc, config: Config) -> tuple[SourceDoc, list[str]]:
    """Remove the sections named in drop_sections; return the rest and what was removed."""
    wanted = {normalize(name) for name in config.drop_sections}
    kept, dropped, dropping = [], [], False
    for block in doc.blocks:
        if block.kind == "heading":
            dropping = normalize(block.text) in wanted
        (dropped if dropping else kept).append(block)
    removed = [f"{block.kind}: {block.text}" for block in dropped]
    return SourceDoc(kept, doc.links), removed
