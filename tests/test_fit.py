import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from cvforge.check.ats import run_checks
from cvforge.cli import app
from cvforge.config import Config, resource
from cvforge.models import Resume
from cvforge.render.fit import FLOORS, MAX_COMPILES, fit, steps
from cvforge.render.typst_renderer import list_themes, load_theme
from cvforge.render.view import build_view
from cvforge.yaml_io import dump_resume, load_resume

runner = CliRunner()
EXAMPLE = resource("examples/resume.yaml")
THEMES = list(list_themes())


def resume_with(bullets: int) -> Resume:
    """A synthetic resume whose length is set by the number of bullets."""
    text = (
        "Built an efficient PySpark workflow on Kubernetes that processed batch number {} nightly."
    )
    return Resume.model_validate(
        {
            "basics": {"name": "Jane Doe", "email": "jane@example.com"},
            "summary": "Data engineer building efficient pipelines.",
            "experience": [
                {
                    "company": "Example Corp",
                    "title": "Data Engineer",
                    "start": "2020-01",
                    "end": "present",
                    "bullets": [text.format(n) for n in range(bullets)],
                }
            ],
        }
    )


def pages(path) -> int:
    return len(PdfReader(path).pages)


def test_themes_are_listed_with_descriptions():
    themes = list_themes()
    assert list(themes) == ["classic", "compact", "modern"]
    assert all(description and not description.startswith("#") for description in themes.values())


@pytest.mark.parametrize("theme", THEMES)
def test_steps_tighten_in_order_and_stay_within_floors(theme):
    tokens = load_theme(theme)
    plan = steps(tokens)
    assert 0 < len(plan) <= MAX_COMPILES - 1
    order = [key for key in plan[-1]]  # dicts keep the order tokens were first lowered in
    expected = ["section_gap", "entry_gap", "item_gap", "line_height", "body_size", "margin"]
    assert order == [key for key in expected if key in order]
    assert plan[-1]["body_size"] == FLOORS["body_size"] and plan[-1]["margin"] == FLOORS["margin"]
    for earlier, later in zip(plan, plan[1:], strict=False):
        assert all(later[key] <= value for key, value in earlier.items())  # never loosened again
    assert all(value >= FLOORS[key] for step in plan for key, value in step.items())


@pytest.mark.parametrize("theme", THEMES)
def test_every_theme_passes_the_ats_check(theme, tmp_path):
    resume = load_resume(EXAMPLE)
    out = tmp_path / "resume.pdf"
    report = fit(build_view(resume, Config()), theme, "a4", out, limit=2)
    assert report.fits and report.adjustments == {} and report.compiles == 1
    results, _ = run_checks(out, Config(), resume)
    assert not [r for r in results if r.status == "fail"], [r.details for r in results]
    fonts = {
        font.get_object()["/BaseFont"]
        for page in PdfReader(out).pages
        for font in page["/Resources"]["/Font"].values()
    }
    family = load_theme(theme)["font"].replace(" ", "")
    assert fonts and all(family in name for name in fonts)  # only the bundled theme font


def test_slightly_oversized_resume_is_tightened_to_fit(tmp_path):
    out = tmp_path / "resume.pdf"
    config = Config()
    # the first length that spills onto a second page with the theme as designed
    count = next(
        n
        for n in range(30, 80)
        if fit(build_view(resume_with(n), config), "classic", "a4", out, limit=1).compiles > 1
    )
    resume = resume_with(count)
    report = fit(build_view(resume, config), "classic", "a4", out, limit=1)
    assert report.fits and pages(out) == 1
    assert report.adjustments and 1 < report.compiles <= MAX_COMPILES
    assert "section_gap" in report.adjustments  # spacing is always the first thing to give
    text = " ".join(PdfReader(out).pages[0].extract_text().split())
    assert all(bullet in text for bullet in resume.experience[0].bullets)


def test_hopelessly_oversized_resume_reports_overflow_and_drops_nothing(tmp_path):
    out = tmp_path / "resume.pdf"
    resume = resume_with(150)
    report = fit(build_view(resume, Config()), "classic", "a4", out, limit=1)
    assert not report.fits and report.pages == pages(out) > 1
    assert report.lines_over > 0 and report.adjustments == {}
    assert report.longest_sections[0].startswith("Experience (")
    assert len(report.longest_bullets) == 3
    assert report.compiles <= MAX_COMPILES + 1  # the last compile restores the designed layout
    text = " ".join(" ".join(page.extract_text() for page in PdfReader(out).pages).split())
    assert all(bullet in text for bullet in resume.experience[0].bullets)


def test_nearly_empty_last_page_is_warned_about(tmp_path):
    out = tmp_path / "resume.pdf"
    config = Config()
    count = next(
        n
        for n in range(30, 80)
        if fit(build_view(resume_with(n), config), "classic", "a4", out, limit=2).pages == 2
    )
    report = fit(build_view(resume_with(count), config), "classic", "a4", out, limit=2)
    assert report.fits and report.last_page_fill < 0.15
    assert "last page is only" in report.warnings[0]


def test_pages_option_fails_loudly_when_content_cannot_fit(tmp_path):
    yaml_path = tmp_path / "resume.yaml"
    dump_resume(resume_with(150), yaml_path)
    result = runner.invoke(app, ["render", str(yaml_path), "--pages", "1", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert "Does not fit 1 page(s)" in result.output and "Longest bullets" in result.output
    assert "limit is 1" in result.output  # the ATS check agrees
    assert runner.invoke(app, ["render", str(yaml_path), "--pages", "0"]).exit_code == 2


def test_themes_preview_renders_every_theme(tmp_path):
    result = runner.invoke(app, ["themes", "--preview", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    for theme in THEMES:
        png = tmp_path / f"{theme}-1.png"
        assert png.read_bytes().startswith(b"\x89PNG"), theme
        assert theme in result.output
