"""PDF -> SourceDoc, as a last resort. A PDF holds positioned text, not structure, so this is
the plain-text parser run on the extracted text; prefer the HTML or LaTeX source if you have it."""

from pathlib import Path

from cvforge.check.extract_text import pdf_text
from cvforge.config import Config
from cvforge.ingest.sourcedoc import SourceDoc
from cvforge.ingest.text import parse_text


def parse_pdf(path: Path, config: Config) -> SourceDoc:
    return parse_text(pdf_text(path), config)
