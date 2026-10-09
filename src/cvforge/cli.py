"""cvforge command line. Exit codes: 0 ok, 1 checks failed, 2 usage or input error."""

import json
import re
import shutil
import sys
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from ruamel.yaml import YAMLError

from cvforge.check.ats import run_checks
from cvforge.check.extract_text import PRIMARY
from cvforge.check.report import check_section, print_checks, print_lint, update_report
from cvforge.config import CONFIG_NAME, Config, load_config, resource
from cvforge.extract.llm import extract_llm
from cvforge.extract.rules import extract
from cvforge.ingest import load_source
from cvforge.ingest.sourcedoc import split_dropped
from cvforge.lint import lint as lint_resume
from cvforge.models import Meta, Resume
from cvforge.render.fit import FitReport, fit
from cvforge.render.typst_renderer import list_themes, render_png
from cvforge.render.view import build_view
from cvforge.verify import passed, verification_state, verify, write_sidecar
from cvforge.yaml_io import dump_resume, load_resume

app = typer.Typer(no_args_is_help=True, add_completion=False)
err = Console(stderr=True)
console = Console()

_TOOLS = ("career-ops", "ai-job-search")
SourceArg = Annotated[Path, typer.Argument(help="Source resume (.html or .tex).")]
ThemeOpt = Annotated[str | None, typer.Option(help="Theme name; default from config.")]
PagesOpt = Annotated[
    int | None, typer.Option(min=1, help="Maximum pages; the layout is tightened to fit.")
]


class Extractor(StrEnum):
    rules = "rules"
    anthropic = "anthropic"


ExtractorOpt = Annotated[
    Extractor, typer.Option(help="rules is deterministic; anthropic calls the Claude API.")
]


@app.callback()
def main() -> None:
    """Deterministic, ATS-safe resume formatter."""
    # Reports quote resume text verbatim; a legacy Windows code page must not crash on it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _fail(message: str, exc: Exception | None = None, code: int = 2) -> typer.Exit:
    detail = f" {escape(str(exc))}" if exc else ""
    err.print(f"[red]{escape(message)}[/red]{detail}", highlight=False)
    return typer.Exit(code)


def _load_resume(path: Path) -> Resume:
    try:
        return load_resume(path)
    except (OSError, YAMLError, ValidationError) as exc:
        raise _fail(f"Cannot read {path}:", exc) from exc


def output_stem(resume: Resume, config: Config) -> str:
    """Jane_Doe_Resume, plus _Acme when company_suffix is on."""
    parts = [*resume.basics.name.split(), "Resume"]
    if config.company_suffix and resume.meta.target_company:
        parts += resume.meta.target_company.split()
    return "_".join(filter(None, (re.sub(r"\W", "", part) for part in parts)))


def _out_dir(resume: Resume, yaml_path: Path) -> Path:
    source = Path(resume.meta.source_file) if resume.meta.source_file else yaml_path
    return Path("out") / source.stem


def _check(pdf: Path, config: Config, resume: Resume | None, jd: str | None = None) -> None:
    """Run the ATS check, save ats_view.txt and report.json beside the PDF, exit 1 on failure."""
    results, texts = run_checks(pdf, config, resume, jd)
    (pdf.parent / "ats_view.txt").write_text(texts[PRIMARY], encoding="utf-8")
    update_report(pdf.parent / "report.json", check=check_section(pdf, results, list(texts)))
    print_checks(results, console)
    if not passed(results):
        raise typer.Exit(1)


def _ingest(
    source: Path, config: Config, yaml_path: Path, extractor: Extractor = Extractor.rules
) -> bool:
    """Source -> resume.yaml, then verify it. Returns whether verification passed."""
    try:
        doc, dropped = split_dropped(load_source(source, config), config)
        tool = next((t for t in _TOOLS if t in source.resolve().parts), "other")
        meta = Meta(source_file=source.as_posix(), source_tool=tool)
        mapper = extract_llm if extractor is Extractor.anthropic else extract
        extraction = mapper(doc, config, meta)
    except (OSError, ValueError) as exc:  # a pydantic ValidationError is a ValueError
        raise _fail(f"Cannot ingest {source}:", exc) from exc
    except Exception as exc:  # the anthropic SDK's errors: missing key, network, API status
        if extractor is not Extractor.anthropic:
            raise
        raise _fail("The anthropic extractor failed:", exc) from exc
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    dump_resume(extraction.resume, yaml_path)
    print(f"wrote {yaml_path}")
    for title, items in (
        ("Dropped (drop_sections in cvforge.toml)", dropped),
        ("Could not map; kept verbatim as an extra section", extraction.unplaced),
    ):
        if items:
            console.print(f"[yellow]{title}:[/yellow]")
            for item in items:
                console.print(f"  - {escape(item)}", highlight=False)
    results = verify(doc, load_resume(yaml_path), config)  # verify what was actually written
    write_sidecar(yaml_path, source, results)
    update_report(
        yaml_path.parent / "report.json",
        source=source.as_posix(),
        ingest={"dropped": dropped, "unplaced": extraction.unplaced},
        verify=check_section(None, results),
    )
    print_checks(results, console, "Faithfulness")
    return passed(results)


def _print_fit(report: FitReport) -> None:
    """Say what fitting did; on failure, how far over the resume is and what is longest."""
    for token, change in report.adjustments.items():
        console.print(f"fit: {token} {change}", highlight=False)
    if not report.fits:
        err.print(
            f"[red]Does not fit {report.limit} page(s):[/red] about {report.lines_over} line(s) "
            "over even at the tightest layout. Nothing was dropped; shorten the content, "
            "raise --pages, or try --theme compact.",
            highlight=False,
        )
        for title, items in (
            ("Longest sections", report.longest_sections),
            ("Longest bullets", report.longest_bullets),
        ):
            err.print(f"  {title}:")
            for item in items:
                err.print(f"    - {escape(item)}", highlight=False)
    for warning in report.warnings:
        err.print(f"[yellow]fit: {warning}[/yellow]", highlight=False)


def _render(
    yaml_path: Path, theme: str | None, out: Path | None, force: bool, pages: int | None = None
) -> None:
    config = load_config()
    if pages:
        config = config.model_copy(update={"pages": pages})
    theme = theme or config.theme
    resume = _load_resume(yaml_path)
    state = verification_state(yaml_path) if resume.meta.source_file else "manual"
    if state in ("failed", "unverified"):
        if not force:
            raise _fail(
                f"{yaml_path} is {state} against its source; fix it or use --force.", code=1
            )
        err.print(f"[yellow]Rendering although verification is {state} (--force).[/yellow]")
    elif state == "edited":
        err.print("[yellow]resume.yaml was edited after it passed verification.[/yellow]")
    pdf = (out or _out_dir(resume, yaml_path)) / f"{output_stem(resume, config)}.pdf"
    try:
        report = fit(build_view(resume, config), theme, config.paper, pdf, config.pages)
    except FileNotFoundError as exc:
        raise _fail(f"Unknown theme {theme!r}:", exc) from exc
    print(f"wrote {pdf} ({report.pages} page(s), theme {theme})")
    _print_fit(report)
    update_report(pdf.parent / "report.json", verification=state, theme=theme, fit=asdict(report))
    _check(pdf, config, resume)


@app.command()
def schema() -> None:
    """Print the JSON Schema of resume.yaml."""
    print(json.dumps(Resume.model_json_schema(), indent=2))


@app.command()
def ingest(
    source: SourceArg,
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Where to write the YAML.")
    ] = None,
    extractor: ExtractorOpt = Extractor.rules,
) -> None:
    """Map a source resume to resume.yaml, then verify it against the source."""
    yaml_path = output or Path("out") / source.stem / "resume.yaml"
    if not _ingest(source, load_config(), yaml_path, extractor):
        raise typer.Exit(1)


@app.command(name="verify")
def verify_command(
    source: SourceArg,
    yaml_path: Annotated[Path, typer.Argument(help="The resume.yaml mapped from it.")],
) -> None:
    """Check that a resume.yaml says exactly what its source says."""
    config = load_config()
    resume = _load_resume(yaml_path)
    try:
        doc, _ = split_dropped(load_source(source, config), config)
    except (OSError, ValueError) as exc:
        raise _fail(f"Cannot read {source}:", exc) from exc
    results = verify(doc, resume, config)
    write_sidecar(yaml_path, source, results)
    update_report(yaml_path.parent / "report.json", verify=check_section(None, results))
    print_checks(results, console, "Faithfulness")
    if not passed(results):
        raise typer.Exit(1)


@app.command()
def lint(yaml_path: Annotated[Path, typer.Argument(help="The resume.yaml to lint.")]) -> None:
    """Print style warnings for a resume.yaml. Warnings only; nothing is changed."""
    print_lint(lint_resume(_load_resume(yaml_path)), console)


@app.command()
def render(
    yaml_path: Annotated[Path, typer.Argument(help="The resume.yaml to render.")],
    theme: ThemeOpt = None,
    out: Annotated[Path | None, typer.Option(help="Output directory.")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Render even if verification failed.")
    ] = False,
    pages: PagesOpt = None,
) -> None:
    """Render a resume.yaml to PDF, then run the ATS check on it."""
    _render(yaml_path, theme, out, force, pages)


@app.command()
def check(
    pdf: Annotated[Path, typer.Argument(help="The PDF to check.")],
    yaml_path: Annotated[
        Path | None, typer.Option("--yaml", help="The resume.yaml it was rendered from.")
    ] = None,
    jd: Annotated[
        Path | None, typer.Option(help="Job description text file, for keyword coverage.")
    ] = None,
) -> None:
    """Check what an ATS parser would see in a PDF. Name and content checks need --yaml."""
    resume = _load_resume(yaml_path) if yaml_path else None
    try:
        jd_text = jd.read_text(encoding="utf-8") if jd else None
        if not pdf.is_file():
            raise FileNotFoundError(pdf)
    except OSError as exc:
        raise _fail("Cannot read:", exc) from exc
    _check(pdf, load_config(), resume, jd_text)


@app.command()
def run(source: SourceArg, theme: ThemeOpt = None, pages: PagesOpt = None) -> None:
    """The everyday command: ingest, verify, lint, render and check one source resume."""
    yaml_path = Path("out") / source.stem / "resume.yaml"
    if not _ingest(source, load_config(), yaml_path):
        raise _fail("Verification failed; nothing was rendered.", code=1)
    warnings = lint_resume(load_resume(yaml_path))
    update_report(
        yaml_path.parent / "report.json",
        lint=[f"{w.location}: {w.rule}: {w.message}" for w in warnings],
    )
    print_lint(warnings, console)
    _render(yaml_path, theme, None, force=False, pages=pages)


@app.command()
def themes(
    preview: Annotated[
        bool, typer.Option("--preview", help="Render the example resume in every theme.")
    ] = False,
    out: Annotated[Path, typer.Option(help="Where --preview writes its PNGs.")] = Path(
        "out/themes"
    ),
) -> None:
    """List the themes; with --preview, render each one to PNG for comparison."""
    config = load_config()
    view = build_view(load_resume(resource("examples/resume.yaml")), config)
    for name, description in list_themes().items():
        default = " (default)" if name == config.theme else ""
        console.print(f"[bold]{name}[/bold]{default}: {escape(description)}", highlight=False)
        if preview:
            for png in render_png(view, name, config.paper, out):
                print(f"  wrote {png}")


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
        raise _fail(f"Refusing to overwrite: {', '.join(existing)} (use --force)")
    directory.mkdir(parents=True, exist_ok=True)
    for dest, src in files.items():
        shutil.copyfile(src, dest)
        print(f"created {dest}")
