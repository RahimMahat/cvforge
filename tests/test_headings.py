from pathlib import Path

from pypdf import PdfReader
from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.config import Config
from cvforge.extract.rules import extract, source_headings
from cvforge.ingest import load_source
from cvforge.ingest.sourcedoc import split_dropped
from cvforge.models import Meta, Resume
from cvforge.render.typst_renderer import render_pdf
from cvforge.render.view import build_view
from cvforge.verify import verify

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = Config()


def load(name: str):
    return split_dropped(load_source(FIXTURES / name, CONFIG), CONFIG)[0]


def test_source_headings_are_recorded_per_section():
    assert source_headings(load("career_ops.html"), CONFIG) == {
        "summary": "Professional Summary",
        "experience": "Work Experience",
        "projects": "Technical Contributions",  # known only from the project markup under it
        "education": "Education",
        "certifications": "Certifications",
        "skills": "Skills",
    }
    latex = source_headings(load("moderncv.tex"), CONFIG)
    assert latex["experience"] == "Professional Experience"
    assert "summary" not in latex  # the LaTeX summary has no heading of its own


def test_keep_heading_text_renders_the_source_wording():
    doc = load("career_ops.html")
    meta = Meta(headings=source_headings(doc, CONFIG))
    resume = extract(doc, CONFIG, meta).resume

    def headings(config: Config) -> list[str]:
        return [section["heading"] for section in build_view(resume, config)["sections"]]

    assert headings(CONFIG) == [
        "Summary",
        "Core Competencies",
        "Skills",
        "Experience",
        "Projects",
        "Education",
        "Certifications",
    ]
    assert headings(Config(keep_heading_text=True)) == [
        "Professional Summary",
        "Core Competencies",
        "Skills",
        "Work Experience",
        "Technical Contributions",
        "Education",
        "Certifications",
    ]


def test_an_invented_heading_fails_verification():
    doc = load("career_ops.html")
    resume = extract(doc, CONFIG, Meta(headings=source_headings(doc, CONFIG))).resume
    assert not [r for r in verify(doc, resume, CONFIG) if r.status == "fail"]
    resume.meta.headings["experience"] = "Career Highlights"
    failed = {r.name: r.details for r in verify(doc, resume, CONFIG) if r.status == "fail"}
    assert failed == {"No additions": ["meta.headings.experience: 'Career Highlights'"]}


def test_keep_heading_text_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cvforge.toml").write_text("keep_heading_text = true\n", encoding="utf-8")
    result = runner.invoke(app, ["run", str(FIXTURES / "career_ops.html")])
    assert result.exit_code == 0, result.output
    seen = (tmp_path / "out" / "career_ops" / "ats_view.txt").read_text(encoding="utf-8")
    assert "WORK EXPERIENCE" in seen and "TECHNICAL CONTRIBUTIONS" in seen
    assert "non-standard heading: 'Work Experience'" in " ".join(result.output.split())
    yaml_text = (tmp_path / "out" / "career_ops" / "resume.yaml").read_text(encoding="utf-8")
    assert "experience: Work Experience" in yaml_text


def test_wrapped_lines_never_end_on_a_separator(tmp_path):
    links = [{"url": f"https://example.com/profile-number-{n}/jane-doe"} for n in range(6)]
    tags = [f"Competency number {n} of many" for n in range(9)]
    resume = Resume.model_validate(
        {
            "basics": {"name": "Jane Doe", "email": "jane@example.com", "links": links},
            "extra_sections": [{"title": "Core Competencies", "items": tags}],
        }
    )
    for theme in ("classic", "modern"):
        out = tmp_path / f"{theme}.pdf"
        render_pdf(build_view(resume, CONFIG), theme, "a4", out)
        lines = [line.strip() for line in PdfReader(out).pages[0].extract_text().splitlines()]
        assert sum(" | " in line for line in lines) >= 4, lines  # both blocks really wrapped
        assert not [line for line in lines if line.endswith("|") or line.startswith("|")], lines
        text = " ".join(lines)
        assert all(tag in text for tag in tags)
        assert all(link["url"].removeprefix("https://") in text for link in links)
