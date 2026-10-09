"""cvforge command line. Exit codes: 0 ok, 1 checks failed, 2 usage or input error."""

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from cvforge.config import CONFIG_NAME, resource
from cvforge.models import Resume

app = typer.Typer(no_args_is_help=True, add_completion=False)
err = Console(stderr=True)


@app.callback()
def main() -> None:
    """Deterministic, ATS-safe resume formatter."""


@app.command()
def schema() -> None:
    """Print the JSON Schema of resume.yaml."""
    print(json.dumps(Resume.model_json_schema(), indent=2))


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Where to create the files.")] = Path("."),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Create cvforge.toml and an example resume.yaml."""
    files = {
        directory / CONFIG_NAME: resource("cvforge.toml.example"),
        directory / "resume.yaml": resource("examples/resume.yaml"),
    }
    existing = [str(dest) for dest in files if dest.exists()]
    if existing and not force:
        err.print(f"[red]Refusing to overwrite:[/red] {', '.join(existing)} (use --force)")
        raise typer.Exit(2)
    directory.mkdir(parents=True, exist_ok=True)
    for dest, src in files.items():
        shutil.copyfile(src, dest)
        print(f"created {dest}")
