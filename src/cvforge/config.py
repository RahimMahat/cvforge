"""cvforge.toml settings and bundled-resource lookup."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONFIG_NAME = "cvforge.toml"

DEFAULT_SECTION_ORDER = [
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "awards",
    "publications",
    "languages",
    "extra_sections",
]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: str = "classic"
    pages: int = Field(default=2, ge=1)
    paper: Literal["a4", "us-letter"] = "a4"
    formats: list[Literal["pdf", "docx", "txt", "md"]] = ["pdf", "docx", "txt", "md"]
    date_format: str = "%b %Y"  # Jun 2023
    section_order: list[str] = DEFAULT_SECTION_ORDER
    company_suffix: bool = False
    max_file_mb: float = 2.0


def load_config(path: Path | None = None) -> Config:
    """Read cvforge.toml (default: current directory); defaults if it doesn't exist."""
    path = path or Path(CONFIG_NAME)
    if not path.exists():
        return Config()
    return Config.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


def resource(rel: str) -> Path:
    """A bundled file: under _data/ in an installed wheel, the repo root in a checkout."""
    pkg = Path(__file__).parent
    for base in (pkg / "_data", pkg.parents[1]):
        if (base / rel).exists():
            return base / rel
    raise FileNotFoundError(f"bundled resource not found: {rel}")
