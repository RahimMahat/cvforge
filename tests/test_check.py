import json

import pytest
from typer.testing import CliRunner

from cvforge.check.ats import (
    contact_problems,
    content_problems,
    glyph_problems,
    heading_problems,
    hygiene_problems,
    jd_coverage,
    link_target_problems,
    name_problems,
    run_checks,
)
from cvforge.cli import app
from cvforge.config import Config, resource
from cvforge.render.typst_renderer import render_pdf
from cvforge.render.view import build_view, flatten
from cvforge.textnorm import normalize, tech_tokens
from cvforge.yaml_io import load_resume

runner = CliRunner()
EXAMPLE = resource("examples/resume.yaml")


@pytest.fixture(scope="module")
def resume():
    return load_resume(EXAMPLE)


@pytest.fixture(scope="module")
def pdf(resume, tmp_path_factory):
    out = tmp_path_factory.mktemp("check") / "Jane_Doe_Resume.pdf"
    render_pdf(build_view(resume, Config()), "classic", "a4", out)
    return out


def test_normalize():
    assert normalize("  **Built**  “AWS” – Glue\n• it’s ") == 'built "aws" - glue it\'s'


def test_tech_tokens():
    text = "Built PySpark jobs on AWS S3 with CI/CD, C# and Node.js. Then Python again on AWS."
    assert tech_tokens(text) == ["PySpark", "AWS", "S3", "CI/CD", "C#", "Node.js"]


def test_all_checks_pass_on_classic_render(pdf, resume):
    results, texts = run_checks(pdf, Config(), resume)
    by_name = {r.name: r for r in results}
    assert {"pdfplumber", "pypdf"} <= set(texts)
    for name in ("Name", "Contact", "Content and order", "Glyphs", "PDF hygiene"):
        assert by_name[name].status == "pass", by_name[name].details
    # the example's Volunteering section is a non-standard heading: a warning, never a failure
    assert by_name["Headings"].status == "warn"
    assert not [r for r in results if r.status == "fail"]


def test_name_must_be_in_first_two_lines():
    assert name_problems("Jane Doe", "Jane Doe\nEngineer\n") == []
    assert name_problems("Jane Doe", "Curriculum Vitae\nPage 1\nJane Doe\n")


def test_contact(resume):
    text = "jane@example.com | +91 90000 00000 | linkedin.com/in/janedoe | github.com/janedoe"
    assert contact_problems(resume, text) == []
    assert contact_problems(resume, text.replace("jane@", "jane at ")) == [
        "not extractable: 'jane@example.com'"
    ]
    assert contact_problems(resume, text.replace("github.com/janedoe", "GitHub")) == [
        "not extractable: 'github.com/janedoe'"
    ]
    # without a YAML, fall back to spotting any email and phone
    assert contact_problems(None, text) == []
    assert contact_problems(None, "no contact here") == [
        "no email address found",
        "no phone number found",
    ]


def test_link_targets_are_clickable(pdf, resume):
    assert link_target_problems(resume, pdf) == []
    other = resume.model_copy(deep=True)
    other.basics.links[0].url = "https://example.org/elsewhere"
    assert link_target_problems(other, pdf) == [
        "no clickable link to 'https://example.org/elsewhere'"
    ]


def test_content_missing_and_out_of_order():
    expected = [("heading", "Skills"), ("bullet", "Built **AWS Glue** pipelines"), ("text", "2022")]
    assert content_problems(expected, "SKILLS\n• Built AWS Glue pipelines\n2022") == ([], [])
    missing, misplaced = content_problems(expected, "2022\nSKILLS\n• Built AWS Glue pipelines")
    assert (missing, misplaced) == ([], ["text: '2022'"])
    missing, misplaced = content_problems(expected, "SKILLS\n2022")
    assert (missing, misplaced) == (["bullet: 'Built **AWS Glue** pipelines'"], [])


def test_content_check_catches_a_dropped_bullet(pdf, resume):
    edited = resume.model_copy(deep=True)
    edited.experience[0].bullets.append("Shipped a streaming platform nobody rendered.")
    results, _ = run_checks(pdf, Config(), edited)
    content = next(r for r in results if r.name == "Content and order")
    assert content.status == "fail"
    assert all("nobody rendered" in detail for detail in content.details)


def test_glyphs():
    assert glyph_problems("efficient workflow, on-call team\n- dash list") == []
    assert glyph_problems("eﬃcient workﬂow") == ["ligature glyph 'ﬂ'", "ligature glyph 'ﬃ'"]
    assert len(glyph_problems("bad � and ")) == 2
    assert glyph_problems("an effi-\ncient pipeline")[0].startswith("word broken by a hyphen")


def test_headings(resume):
    assert heading_problems(["Summary", "Experience"], "") == []
    assert heading_problems(["Core Competencies"], "") == [
        "non-standard heading: 'Core Competencies'"
    ]
    assert heading_problems(None, "Jane\nEXPERIENCE\nEDUCATION\n") == []
    assert heading_problems(None, "Jane\nWhere I worked\n") == [
        "no 'Experience' heading found",
        "no 'Education' heading found",
    ]


def test_hygiene(pdf):
    assert hygiene_problems(pdf, Config()) == []
    problems = hygiene_problems(pdf, Config(paper="us-letter", max_file_mb=0.001))
    assert len(problems) == 2
    assert "expected us-letter" in problems[0]
    assert "limit is 0.001 MB" in problems[1]


def test_jd_coverage_is_informational():
    result = jd_coverage("We use PySpark, AWS and Snowflake.", "built pyspark jobs on aws")
    assert result.status == "info"
    assert result.details == ["found: PySpark, AWS", "missing: Snowflake"]


def test_render_writes_report_and_ats_view(tmp_path):
    result = runner.invoke(app, ["render", str(EXAMPLE), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["check"]
    assert report["passed"] is True
    assert {"pdfplumber", "pypdf"} <= set(report["extractors"])
    assert {c["name"] for c in report["checks"]} >= {"Name", "Contact", "Glyphs", "PDF hygiene"}
    view = (tmp_path / "ats_view.txt").read_text(encoding="utf-8")
    assert view.startswith("Jane Doe") and "₹12L" in view


def test_check_command_exit_codes(pdf, tmp_path):
    assert runner.invoke(app, ["check", str(pdf), "--yaml", str(EXAMPLE)]).exit_code == 0
    assert runner.invoke(app, ["check", str(tmp_path / "missing.pdf")]).exit_code == 2
    # a YAML the PDF was not rendered from fails the content check
    other = tmp_path / "other.yaml"
    other.write_text("basics:\n  name: Someone Else\n", encoding="utf-8")
    assert runner.invoke(app, ["check", str(pdf), "--yaml", str(other)]).exit_code == 1


def test_flatten_reads_in_page_order(resume):
    kinds = [kind for kind, _ in flatten(build_view(resume, Config()))]
    assert kinds[0] == "name" and kinds.count("heading") == 8
