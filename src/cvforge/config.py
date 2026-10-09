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


# Source heading (lowercase) -> schema section. Anything else becomes an extra section.
HEADING_SYNONYMS = {
    "summary": ["summary", "professional summary", "profile", "about", "about me", "objective"],
    "skills": ["skills", "technical skills", "tech stack", "technologies"],
    "experience": [
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
    ],
    "projects": ["projects", "personal projects", "selected projects", "side projects"],
    "education": ["education", "academic background", "qualifications"],
    "certifications": ["certifications", "certificates", "licenses and certifications"],
    "awards": ["awards", "honors", "honours", "achievements"],
    "publications": ["publications"],
    "languages": ["languages"],
}

# HTML class -> role. "entry:<section>" marks the element that wraps one entry.
# Roles: name, heading, contact, org, title, dates, location, description, tech, details,
# category, skill, item, skip.
HTML_CLASSES = {
    "section-title": "heading",
    "contact-row": "contact",
    "separator": "skip",
    "competency-tag": "item",
    "job": "entry:experience",
    "job-company": "org",
    "job-period": "dates",
    "job-role": "title",
    "job-location": "location",
    "project": "entry:projects",
    "project-title": "title",
    "project-desc": "description",
    "project-tech": "tech",
    "edu-item": "entry:education",
    "edu-title": "title",
    "edu-org": "org",
    "edu-year": "dates",
    "edu-desc": "details",
    "cert-item": "entry:certifications",
    "cert-title": "title",
    "cert-org": "org",
    "cert-year": "dates",
    "award-item": "entry:awards",
    "award-title": "title",
    "award-org": "org",
    "award-year": "dates",
    "skill-item": "skill",
    "skill-category": "category",
}

# LaTeX macro -> the role of each {argument}. "" ignores an argument, "body" is parsed as
# content. Header roles: name, location, phone, email, links. Entry roles as for HTML.
LATEX_MACROS = {
    "name": ["name", "name"],
    "address": ["location", "", ""],
    "phone": ["phone"],
    "email": ["email"],
    "extrainfo": ["links"],
    "cventry": ["dates", "title", "org", "location", "", "body"],
    "vspace": [""],
    "needspace": [""],
    "makecvtitle": [],
    "small": [],
}

_MERGED_TABLES = {
    "heading_synonyms": HEADING_SYNONYMS,
    "html_classes": HTML_CLASSES,
    "latex_macros": LATEX_MACROS,
}


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
    drop_sections: list[str] = ["references"]  # source headings to leave out, always reported
    keywords_path: str = "keywords.txt"
    heading_synonyms: dict[str, list[str]] = HEADING_SYNONYMS
    html_classes: dict[str, str] = HTML_CLASSES
    latex_macros: dict[str, list[str]] = LATEX_MACROS

    def section_for(self, heading: str) -> str | None:
        """The schema section a source heading maps to, if any."""
        wanted = " ".join(heading.replace("**", "").lower().split())
        return next((k for k, names in self.heading_synonyms.items() if wanted in names), None)

    def keywords(self) -> list[str]:
        """Extra keywords from keywords_path (in the working directory, else the bundled file)."""
        path = Path(self.keywords_path)
        if not path.exists():
            path = resource("keywords.txt")
        lines = (line.strip() for line in path.read_text("utf-8").splitlines())
        return [line for line in lines if line and not line.startswith("# ")]


def load_config(path: Path | None = None) -> Config:
    """Read cvforge.toml (default: current directory); defaults if it doesn't exist."""
    path = path or Path(CONFIG_NAME)
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for key, defaults in _MERGED_TABLES.items():  # a table in the file adds to the defaults
        if key in data:
            data[key] = {**defaults, **data[key]}
    return Config.model_validate(data)


def resource(rel: str) -> Path:
    """A bundled file: under _data/ in an installed wheel, the repo root in a checkout."""
    pkg = Path(__file__).parent
    for base in (pkg / "_data", pkg.parents[1]):
        if (base / rel).exists():
            return base / rel
    raise FileNotFoundError(f"bundled resource not found: {rel}")
