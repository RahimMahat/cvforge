"""Read a source resume into a SourceDoc, picking the parser by extension then by content."""

from pathlib import Path

from cvforge.config import Config
from cvforge.ingest.html import parse_html
from cvforge.ingest.jsonresume import parse_jsonresume
from cvforge.ingest.latex import parse_latex
from cvforge.ingest.markdown import parse_markdown
from cvforge.ingest.pdf import parse_pdf
from cvforge.ingest.sourcedoc import SourceDoc
from cvforge.ingest.text import parse_text

_BY_SUFFIX = {
    ".html": "html",
    ".htm": "html",
    ".tex": "latex",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "jsonresume",
    ".txt": "text",
    ".pdf": "pdf",
}
_PARSERS = {
    "html": parse_html,
    "latex": parse_latex,
    "markdown": parse_markdown,
    "jsonresume": parse_jsonresume,
    "text": parse_text,
}


def detect_type(path: Path, source: str) -> str:
    if kind := _BY_SUFFIX.get(path.suffix.lower()):
        return kind
    head = source.lstrip()[:2000].lower()
    if head.startswith(("<!doctype html", "<html")):
        return "html"
    if "\\documentclass" in head or "\\begin{document}" in source:
        return "latex"
    if head.startswith("{"):
        return "jsonresume"
    if head.startswith("# "):
        return "markdown"
    supported = ", ".join(sorted(_BY_SUFFIX))
    raise ValueError(f"unsupported input type: {path.name} (supported: {supported})")


def load_source(path: Path, config: Config) -> SourceDoc:
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path, config)
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"unsupported input type: {path.name} is not text") from exc
    return _PARSERS[detect_type(path, source)](source, config)
