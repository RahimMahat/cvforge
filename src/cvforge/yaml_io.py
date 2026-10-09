"""YAML I/O. Round-trip mode keeps comments and key order so hand edits survive."""

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from cvforge.models import Resume

_yaml = YAML()  # round-trip by default
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.width = 100


def load_yaml(path: Path) -> Any:
    return _yaml.load(path.read_text(encoding="utf-8"))


def dump_yaml(data: Any, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        _yaml.dump(data, fh)


def load_resume(path: Path) -> Resume:
    return Resume.model_validate(load_yaml(path))


def dump_resume(resume: Resume, path: Path) -> None:
    """Write a fresh resume.yaml in schema order, leaving out empty fields."""
    data = resume.model_dump(exclude_none=True)
    dump_yaml({k: v for k, v in data.items() if v not in ([], {})}, path)
