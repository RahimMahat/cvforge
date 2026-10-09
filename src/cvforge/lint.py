"""Style warnings for a resume.yaml. Warnings only: nothing here ever changes content."""

import re
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from rapidfuzz import fuzz

from cvforge.models import Resume
from cvforge.textnorm import normalize, tech_tokens

MAX_BULLET_CHARS = 220  # about 2 rendered lines
MAX_SUMMARY_CHARS = (
    420  # ponytail: ~4 lines at ~105 chars; measure the real render if this misfires
)
MAX_SKILL_ITEMS = 35
MAX_KEYWORD_REPEATS = 3
NEAR_DUPLICATE = 90
_WEAK_STARTS = ("responsible for", "worked on", "helped", "assisted")
_PRONOUN_RE = re.compile(r"\b(I|[Mm]y|[Mm]e)\b")
# ponytail: tense is guessed from the first word's shape (no NLP); extend the list if it misses.
_PRESENT_VERBS = {
    "build", "design", "develop", "lead", "manage", "create", "maintain", "write", "own",
    "drive", "support", "work", "implement", "run", "deliver", "automate", "optimize",
}  # fmt: skip
_NOT_VERBS = {"across", "analysis", "business", "process", "status", "this", "its", "always"}


@dataclass
class LintWarning:
    rule: str
    location: str
    message: str


def _months(value: str | None) -> int | None:
    """A sortable month index; 'present' sorts after everything."""
    if value is None:
        return None
    if value == "present":
        return 10**6
    year, _, month = value.partition("-")
    return int(year) * 12 + int(month or 1) - 1


def _is_present_tense(bullet: str) -> bool:
    words = bullet.replace("**", "").split()
    first = words[0].lower().strip(",.:;") if words else ""
    if first in _NOT_VERBS:
        return False
    plural_s = len(first) > 3 and first.endswith("s") and not first.endswith(("ss", "us", "is"))
    return first in _PRESENT_VERBS or first.endswith("ing") or plural_s


def _bullets(resume: Resume) -> list[tuple[str, str]]:
    """(location, bullet) for every bullet in experience and projects."""
    found = []
    for section, entries in (("experience", resume.experience), ("projects", resume.projects)):
        for e, entry in enumerate(entries):
            found += [
                (f"{section}[{e}].bullets[{b}]", text) for b, text in enumerate(entry.bullets)
            ]
    return found


def _date_warnings(resume: Resume) -> list[LintWarning]:
    out = []
    jobs = resume.experience
    for i, job in enumerate(jobs):
        if not (job.start and job.end):
            out.append(LintWarning("missing-date", f"experience[{i}]", "start or end date missing"))
    for i, edu in enumerate(resume.education):
        if not edu.end:
            out.append(LintWarning("missing-date", f"education[{i}]", "end date missing"))
    dates = [d for job in jobs for d in (job.start, job.end) if d and d != "present"]
    if len({"-" in d for d in dates}) > 1:
        out.append(LintWarning("mixed-dates", "experience", "mixes YYYY-MM and YYYY dates"))
    for (i, a), (j, b) in combinations(enumerate(jobs), 2):
        spans = [_months(d) for d in (a.start, a.end, b.start, b.end)]
        if None not in spans and spans[0] < spans[3] and spans[2] < spans[1]:  # type: ignore[operator]
            where = f"experience[{i}] and experience[{j}]"
            out.append(LintWarning("overlapping-dates", where, "date ranges overlap"))
    return out


def lint(resume: Resume) -> list[LintWarning]:
    out: list[LintWarning] = []
    bullets = _bullets(resume)
    for where, text in bullets:
        if len(text) > MAX_BULLET_CHARS:
            out.append(LintWarning("long-bullet", where, f"{len(text)} characters (over ~2 lines)"))
        if text.lower().startswith(_WEAK_STARTS):
            out.append(
                LintWarning("weak-start", where, f"starts with {' '.join(text.split()[:2])!r}")
            )
        if found := _PRONOUN_RE.search(text):
            out.append(
                LintWarning("first-person", where, f"first-person pronoun {found.group()!r}")
            )
    for e, job in enumerate(resume.experience):
        if job.end and job.end != "present":
            for b, text in enumerate(job.bullets):
                if _is_present_tense(text):
                    where = f"experience[{e}].bullets[{b}]"
                    out.append(
                        LintWarning(
                            "tense", where, f"present tense in a past role: {text.split()[0]!r}"
                        )
                    )
    if resume.summary and (found := _PRONOUN_RE.search(resume.summary)):
        out.append(
            LintWarning("first-person", "summary", f"first-person pronoun {found.group()!r}")
        )
    if resume.summary and len(resume.summary) > MAX_SUMMARY_CHARS:
        size = len(resume.summary)
        out.append(LintWarning("long-summary", "summary", f"{size} characters (over ~4 lines)"))

    counts = Counter(k.lower() for _, text in bullets for k in set(tech_tokens(text)))
    for keyword, count in sorted(counts.items()):
        if count > MAX_KEYWORD_REPEATS:
            out.append(
                LintWarning("keyword-repeat", "bullets", f"{keyword!r} is in {count} bullets")
            )
    skill_items = sum(len(group.items) for group in resume.skills)
    if skill_items > MAX_SKILL_ITEMS:
        out.append(LintWarning("many-skills", "skills", f"{skill_items} skill items (over 35)"))

    for (where_a, a), (where_b, b) in combinations(bullets, 2):
        if fuzz.ratio(normalize(a), normalize(b)) >= NEAR_DUPLICATE:
            out.append(
                LintWarning("duplicate-bullet", f"{where_a} and {where_b}", "near-duplicate")
            )
    return out + _date_warnings(resume)
