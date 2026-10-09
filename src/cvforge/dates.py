"""Recognize dates and date ranges in source text and convert them to YYYY-MM / YYYY / present."""

import re

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = rf"(?:{'|'.join(_MONTHS)})[a-z]*\.?,?\s+"
_NUMERIC = r"(?:0?[1-9]|1[0-2])[/.]"
_YEAR = r"(?:19|20)\d{2}"
_OPEN = r"present|current|now|ongoing|till date|to date"
_ISO = rf"{_YEAR}-(?:0[1-9]|1[0-2])(?:-[0-3]\d)?"  # 2024-04 or 2024-04-15
_TOKEN = rf"(?:{_ISO}|(?:{_MONTH}|{_NUMERIC})?{_YEAR}|{_OPEN})"
_RANGE_RE = re.compile(
    rf"(?<![\w/.])({_TOKEN})(?:\s*(?:-|–|—|\bto\b|\buntil\b)\s*({_TOKEN}))?(?![\w/])", re.I
)
_PARTS_RE = re.compile(rf"(?:({_MONTH})|({_NUMERIC}))?({_YEAR})", re.I)

DatePair = tuple[str | None, str | None]


def _iso(token: str) -> str:
    if re.fullmatch(_ISO, token.strip()):
        return token.strip()[:7]
    match = _PARTS_RE.fullmatch(token.strip())
    if not match:
        return "present"
    name, number, year = match.groups()
    if name:
        return f"{year}-{_MONTHS.index(name[:3].lower()) + 1:02d}"
    return f"{year}-{int(number[:-1]):02d}" if number else year


def find_date_ranges(text: str) -> list[tuple[DatePair, tuple[int, int]]]:
    """Every date or date range in the text as ((start, end), (from, to)); a lone date is start."""
    found = []
    for match in _RANGE_RE.finditer(text):
        start, end = match.groups()
        if start.lower() in _OPEN.split("|") and not end:
            continue  # a bare "now" or "current" in prose is not a date
        found.append(((_iso(start), _iso(end) if end else None), match.span()))
    return found


def parse_date_range(text: str) -> DatePair | None:
    """(start, end) if the whole text is one date or date range, else None."""
    ranges = find_date_ranges(text)
    if len(ranges) == 1 and ranges[0][1] == (0, len(text)):
        return ranges[0][0]
    return None
