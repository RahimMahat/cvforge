"""Extract a PDF's text the way independent parsers would see it."""

import shutil
import subprocess
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

PRIMARY = "pdfplumber"
REQUIRED_EXTRACTORS = (PRIMARY, "pypdf")  # always available; pdftotext is optional


def extract_all(pdf: Path) -> dict[str, str]:
    """Text per extractor: pdfplumber (primary), pypdf, and pdftotext when it is installed."""
    with pdfplumber.open(pdf) as doc:
        texts = {PRIMARY: "\n".join(page.extract_text() or "" for page in doc.pages)}
    texts["pypdf"] = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
    if exe := shutil.which("pdftotext"):
        done = subprocess.run(
            [exe, "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=False
        )
        if done.returncode == 0:
            texts["pdftotext"] = done.stdout.decode("utf-8", errors="replace")
    return texts
