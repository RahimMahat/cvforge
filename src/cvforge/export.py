"""Export a Resume to other schemas. Currently: JSON Resume (jsonresume.org)."""

from typing import Any

from cvforge.models import Resume

_SCHEMA = "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json"


def _clean(value: Any) -> Any:
    """Drop empty values and the **bold** markers, which JSON Resume has no notion of."""
    if isinstance(value, dict):
        cleaned = {key: _clean(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value.replace("**", "") if isinstance(value, str) else value


def _end(value: str | None) -> str | None:
    return None if value == "present" else value  # JSON Resume omits endDate for a current role


def to_jsonresume(resume: Resume) -> dict[str, Any]:
    b = resume.basics
    data = {
        "$schema": _SCHEMA,
        "basics": {
            "name": b.name,
            "label": b.headline,
            "email": b.email,
            "phone": b.phone,
            "summary": resume.summary,
            "location": {"address": b.location},
            "profiles": [{"network": link.label, "url": link.url} for link in b.links],
        },
        "work": [
            {
                "name": job.company,
                "position": job.title,
                "location": job.location,
                "startDate": job.start,
                "endDate": _end(job.end),
                "highlights": job.bullets,
            }
            for job in resume.experience
        ],
        "education": [
            {
                "institution": edu.institution,
                "studyType": edu.degree,
                "area": edu.field,
                "startDate": edu.start,
                "endDate": _end(edu.end),
                "courses": edu.details,
            }
            for edu in resume.education
        ],
        "skills": [{"name": s.category, "keywords": s.items} for s in resume.skills],
        "projects": [
            {
                "name": p.name,
                "url": p.url,
                "description": p.description,
                "highlights": p.bullets,
                "keywords": p.tech,
            }
            for p in resume.projects
        ],
        "certificates": [
            {"name": c.name, "issuer": c.issuer, "date": c.date} for c in resume.certifications
        ],
        "awards": [{"title": a.title, "awarder": a.awarder, "date": a.date} for a in resume.awards],
        "publications": [
            {"name": p.name, "publisher": p.publisher, "releaseDate": p.date, "url": p.url}
            for p in resume.publications
        ],
        "languages": [{"language": x.language, "fluency": x.fluency} for x in resume.languages],
        # JSON Resume has no free-form sections; they travel under meta so nothing is lost.
        "meta": {
            "cvforge": {
                "extra_sections": [
                    {"title": extra.title, "items": extra.items} for extra in resume.extra_sections
                ]
            }
        },
    }
    return _clean(data)
