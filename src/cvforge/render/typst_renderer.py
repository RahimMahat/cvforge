"""Compile the render view to PDF or PNG with Typst.

User text never becomes Typst source: the view travels as JSON through sys.inputs
and the template reads it with json(), so no escaping is needed.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

import typst

from cvforge.config import resource


def list_themes() -> dict[str, str]:
    """Theme name -> one-line description (the first comment line of its theme.toml)."""
    found = {}
    for toml in sorted(resource("themes").glob("*/theme.toml")):
        first = toml.read_text(encoding="utf-8").splitlines()[0]
        found[toml.parent.name] = first.lstrip("# ").split(": ", 1)[-1]
    return found


def load_theme(name: str) -> dict[str, Any]:
    return tomllib.loads(resource(f"themes/{name}/theme.toml").read_text(encoding="utf-8"))


def _compile(
    view: dict[str, Any],
    theme: str,
    paper: str,
    out: Path,
    overrides: dict[str, Any] | None = None,
    **options: Any,
) -> None:
    data = {**view, "theme": {**load_theme(theme), **(overrides or {})}, "paper": paper}
    out.parent.mkdir(parents=True, exist_ok=True)
    root = resource("themes")  # templates import ../base.typ, so the root is the themes folder
    typst.compile(
        str(root / theme / "template.typ"),
        output=str(out),
        root=str(root),
        font_paths=[str(resource("fonts"))],
        ignore_system_fonts=True,
        sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
        **options,
    )


def render_pdf(
    view: dict[str, Any],
    theme: str,
    paper: str,
    out: Path,
    overrides: dict[str, Any] | None = None,
) -> None:
    """Render to PDF. `overrides` replaces individual theme tokens (used by page fitting)."""
    _compile(view, theme, paper, out, overrides)


def render_png(view: dict[str, Any], theme: str, paper: str, out_dir: Path) -> list[Path]:
    """Render one PNG per page as <theme>-<page>.png; returns the files written."""
    _compile(view, theme, paper, out_dir / f"{theme}-{{p}}.png", format="png", ppi=110)
    return sorted(out_dir.glob(f"{theme}-*.png"))
