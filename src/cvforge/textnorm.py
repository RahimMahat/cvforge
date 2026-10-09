"""Text normalization and keyword spotting shared by the ATS check, lint and verify."""

import re

_TRANSLATE = str.maketrans(
    {
        **dict.fromkeys("‐‑‒–—―−", "-"),
        **dict.fromkeys("‘’‚′", "'"),
        **dict.fromkeys("“”„″", '"'),
        **dict.fromkeys("•·▪◦‣●∙", " "),
        " ": " ",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#/&-]*")


def normalize(text: str) -> str:
    """Lowercase; unify dashes, quotes and bullet glyphs; drop ** and extra whitespace."""
    return " ".join(text.replace("**", "").translate(_TRANSLATE).lower().split())


def tech_tokens(text: str) -> list[str]:
    """Tech-looking tokens in order of first appearance: PySpark, AWS, S3, CI/CD, C#, Node.js.

    # ponytail: shape heuristic (CamelCase, ALLCAPS, digits, . + # /), not a dictionary;
    # keywords.txt (M4) covers lowercase terms like "dbt".
    """
    seen: dict[str, None] = {}
    for match in _TOKEN_RE.finditer(text.replace("**", "")):
        token = match.group().rstrip(".-/&")
        techy = (
            re.search(r"[a-z][A-Z]", token)  # CamelCase
            or (len(token) > 1 and token.isupper())  # ALLCAPS
            or (re.search(r"\d", token) and re.search(r"[A-Za-z]", token))  # S3, 2TB
            or re.search(r"\w[.+#/]", token)  # C#, C++, Node.js, CI/CD
        )
        if techy:
            seen.setdefault(token)
    return list(seen)
