"""YAML I/O. Round-trip mode keeps comments and key order so hand edits survive."""

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from cvforge.models import Resume

_DATE_KEYS = ("start", "end", "date")
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
    dump_yaml(_prune(resume.model_dump(exclude_none=True)), path)


def _prune(value: Any) -> Any:
    """Drop empty lists and dicts at every level; write bare years as numbers (start: 2018)."""
    if isinstance(value, dict):
        pruned = {key: _prune(item) for key, item in value.items()}
        return {
            key: int(item) if key in _DATE_KEYS and str(item).isdigit() else item
            for key, item in pruned.items()
            if item not in ([], {})
        }
    return [_prune(item) for item in value] if isinstance(value, list) else value
