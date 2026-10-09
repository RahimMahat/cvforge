"""Canonical resume schema: the shape of resume.yaml."""

import re
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

_DATE_PATTERN = r"^(\d{4}(-(0[1-9]|1[0-2]))?|present)$"  # YYYY-MM, YYYY or present
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")
_LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+\{")


def _check_markup(value: str) -> str:
    """`**bold**` is the only inline markup; literal symbols like < > \\ { } are fine."""
    if value.count("**") % 2:
        raise ValueError(f"unbalanced ** in {value!r}")
    if found := _HTML_TAG_RE.search(value) or _LATEX_CMD_RE.search(value):
        raise ValueError(f"markup {found.group()!r} not allowed (only **bold**) in {value!r}")
    return value


# YAML reads a bare `2017` as an int, so coerce before validating.
ResumeDate = Annotated[str, StringConstraints(pattern=_DATE_PATTERN), BeforeValidator(str)]
Text = Annotated[str, AfterValidator(_check_markup)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(_Model):
    source_file: str | None = None
    source_tool: Literal["career-ops", "ai-job-search", "manual", "other"] = "manual"
    target_role: str | None = None
    target_company: str | None = None


class Link(_Model):
    label: str
    url: str
    text: str | None = None  # visible text, if the source showed something shorter than the url


class Basics(_Model):
    name: str
    headline: Text | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[Link] = Field(default_factory=list)


class SkillGroup(_Model):
    category: Text
    items: list[Text]


class Experience(_Model):
    company: Text
    title: Text
    location: Text | None = None
    start: ResumeDate | None = None
    end: ResumeDate | None = None
    bullets: list[Text] = Field(default_factory=list)


class Project(_Model):
    name: Text
    url: str | None = None
    tech: list[Text] = Field(default_factory=list)
    description: Text | None = None
    bullets: list[Text] = Field(default_factory=list)


class Education(_Model):
    institution: Text
    degree: Text | None = None
    field: Text | None = None
    location: Text | None = None
    start: ResumeDate | None = None
    end: ResumeDate | None = None
    details: list[Text] = Field(default_factory=list)


class Certification(_Model):
    name: Text
    issuer: Text | None = None
    date: ResumeDate | None = None


class Award(_Model):
    title: Text
    awarder: Text | None = None
    date: ResumeDate | None = None


class Publication(_Model):
    name: Text
    publisher: Text | None = None
    date: ResumeDate | None = None
    url: str | None = None


class Language(_Model):
    language: Text
    fluency: Text | None = None


class ExtraSection(_Model):
    title: Text
    items: list[Text]


class Resume(_Model):
    meta: Meta = Field(default_factory=Meta)
    basics: Basics
    summary: Text | None = None
    skills: list[SkillGroup] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    extra_sections: list[ExtraSection] = Field(default_factory=list)
