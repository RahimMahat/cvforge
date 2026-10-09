"""PDF -> SourceDoc, as a last resort. A PDF holds positioned text, not structure, so this is
the plain-text parser run on the extracted text; prefer the HTML or LaTeX source if you have it."""

from pathlib import Path

import pdfplumber

from cvforge.config import Config
from cvforge.ingest.sourcedoc import SourceDoc
from cvforge.ingest.text import parse_text


def parse_pdf(path: Path, config: Config) -> SourceDoc:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return parse_text(text, config)
