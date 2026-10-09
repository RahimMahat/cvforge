"""Compile the render view to PDF with Typst.

User text never becomes Typst source: the view travels as JSON through sys.inputs
and the template reads it with json(), so no escaping is needed.
"""

import json
import tomllib
from pathlib import Path
from typing import Any

import typst

from cvforge.config import resource


def load_theme(name: str) -> dict[str, Any]:
    return tomllib.loads(resource(f"themes/{name}/theme.toml").read_text(encoding="utf-8"))


def render_pdf(view: dict[str, Any], theme: str, paper: str, out: Path) -> None:
    data = {**view, "theme": load_theme(theme), "paper": paper}
    out.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(
        str(resource(f"themes/{theme}/template.typ")),
        output=str(out),
        font_paths=[str(resource("fonts"))],
        ignore_system_fonts=True,
        sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
    )
