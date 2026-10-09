"""cvforge command line. Exit codes: 0 ok, 1 checks failed, 2 usage or input error."""

import json
import re
import shutil
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from ruamel.yaml import YAMLError

from cvforge.config import CONFIG_NAME, Config, load_config, resource
from cvforge.models import Resume
from cvforge.render.typst_renderer import render_pdf
from cvforge.render.view import build_view
from cvforge.yaml_io import load_resume

app = typer.Typer(no_args_is_help=True, add_completion=False)
err = Console(stderr=True)


@app.callback()
def main() -> None:
    """Deterministic, ATS-safe resume formatter."""


@app.command()
def schema() -> None:
    """Print the JSON Schema of resume.yaml."""
    print(json.dumps(Resume.model_json_schema(), indent=2))


def _load_resume(path: Path) -> Resume:
    try:
        return load_resume(path)
    except (OSError, YAMLError, ValidationError) as exc:
        err.print(f"[red]Cannot read {path}:[/red] {exc}", markup=True, highlight=False)
        raise typer.Exit(2) from exc


def output_stem(resume: Resume, config: Config) -> str:
    """Jane_Doe_Resume, plus _Acme when company_suffix is on."""
    parts = [*resume.basics.name.split(), "Resume"]
    if config.company_suffix and resume.meta.target_company:
        parts += resume.meta.target_company.split()
    return "_".join(filter(None, (re.sub(r"\W", "", part) for part in parts)))


@app.command()
def render(
    yaml_path: Annotated[Path, typer.Argument(help="The resume.yaml to render.")],
    theme: Annotated[str | None, typer.Option(help="Theme name; default from config.")] = None,
    out: Annotated[Path | None, typer.Option(help="Output directory.")] = None,
) -> None:
    """Render a resume.yaml to PDF."""
    config = load_config()
    theme = theme or config.theme
    resume = _load_resume(yaml_path)
    source = Path(resume.meta.source_file) if resume.meta.source_file else yaml_path
    pdf = (out or Path("out") / source.stem) / f"{output_stem(resume, config)}.pdf"
    try:
        render_pdf(build_view(resume, config), theme, config.paper, pdf)
    except FileNotFoundError as exc:
        err.print(f"[red]Unknown theme {theme!r}:[/red] {exc}")
        raise typer.Exit(2) from exc
    print(f"wrote {pdf}")


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
