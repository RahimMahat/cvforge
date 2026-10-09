"""Extract a PDF's text the way independent parsers would see it."""

import shutil
import subprocess
from pathlib import Path

import pdfplumber
from pypdf import PdfReader
from pypdf.errors import PyPdfError

PRIMARY = "pdfplumber"
REQUIRED_EXTRACTORS = (PRIMARY, "pypdf")  # always available; pdftotext is optional


def pdf_text(pdf: Path) -> str:
    """The PDF's text as pdfplumber reads it. ValueError if the file is not a readable PDF."""
    try:
        with pdfplumber.open(pdf) as doc:
            return "\n".join(page.extract_text() or "" for page in doc.pages)
    except OSError:
        raise
    except Exception as exc:  # pdfplumber and pdfminer raise their own unrelated error types
        raise ValueError(f"{pdf.name} is not a readable PDF") from exc


def extract_all(pdf: Path) -> dict[str, str]:
    """Text per extractor: pdfplumber (primary), pypdf, and pdftotext when it is installed."""
    texts = {PRIMARY: pdf_text(pdf)}
    try:
        texts["pypdf"] = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
    except PyPdfError as exc:
        raise ValueError(f"{pdf.name} is not a readable PDF") from exc
    if exe := shutil.which("pdftotext"):
        done = subprocess.run(
            [exe, "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=False
        )
        if done.returncode == 0:
            texts["pdftotext"] = done.stdout.decode("utf-8", errors="replace")
    return texts
