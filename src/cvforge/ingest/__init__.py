"""Read a source resume into a SourceDoc, picking the parser by extension then by content."""

from pathlib import Path

from cvforge.config import Config
from cvforge.ingest.html import parse_html
from cvforge.ingest.latex import parse_latex
from cvforge.ingest.sourcedoc import SourceDoc

_BY_SUFFIX = {".html": "html", ".htm": "html", ".tex": "latex"}


def detect_type(path: Path, source: str) -> str:
    if kind := _BY_SUFFIX.get(path.suffix.lower()):
        return kind
    head = source.lstrip()[:2000].lower()
    if head.startswith(("<!doctype html", "<html")):
        return "html"
    if "\\documentclass" in head or "\\begin{document}" in source:
        return "latex"
    raise ValueError(f"unsupported input type: {path.name} (supported: .html, .tex)")


def load_source(path: Path, config: Config) -> SourceDoc:
    source = path.read_text(encoding="utf-8")
    parser = {"html": parse_html, "latex": parse_latex}[detect_type(path, source)]
    return parser(source, config)
