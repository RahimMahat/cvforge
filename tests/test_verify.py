from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.config import Config
from cvforge.extract.rules import extract
from cvforge.ingest import load_source
from cvforge.ingest.sourcedoc import split_dropped
from cvforge.models import Meta
from cvforge.verify import passed, verification_state, verify, write_sidecar
from cvforge.yaml_io import dump_resume

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = Config()


@pytest.fixture(params=["career_ops.html", "moderncv.tex"])
def case(request):
    doc, _ = split_dropped(load_source(FIXTURES / request.param, CONFIG), CONFIG)
    return doc, extract(doc, CONFIG, Meta(source_file=request.param)).resume


def failures(doc, resume) -> dict[str, list[str]]:
    return {r.name: r.details for r in verify(doc, resume, CONFIG) if r.status == "fail"}


def test_untouched_extraction_passes(case):
    assert failures(*case) == {}


def test_added_metric_fails(case):
    doc, resume = case
    resume.experience[0].bullets[0] += " Saved $2M a year."
    failed = failures(doc, resume)
    assert failed["Numbers"] == ["'$2M' is not in the source"]


def test_added_bullet_fails(case):
    doc, resume = case
    resume.experience[0].bullets.append("Mentored a team of engineers across offices.")
    failed = failures(doc, resume)
    assert "Mentored a team of engineers" in failed["No additions"][0]
    assert failed["No additions"][0].startswith("experience[0].bullets[3]")


def test_dropped_keyword_fails(case):
    doc, resume = case
    bullets = resume.experience[0].bullets
    bullets[1] = bullets[1].replace("Terraform", "IaC tooling")
    failed = failures(doc, resume)
    assert set(failed) >= {"Coverage", "No additions"}  # the bullet no longer matches its source


def test_keyword_lost_from_the_whole_resume_is_named(case):
    doc, resume = case
    text = resume.model_dump_json().replace("Redshift", "the warehouse")
    edited = type(resume).model_validate_json(text)
    assert "'redshift' is missing" in failures(doc, edited)["Keywords"]


def test_paraphrased_bullet_fails(case):
    doc, resume = case
    original = resume.experience[1].bullets[0]
    resume.experience[1].bullets[0] = "Improved the data warehouse so that dashboards ran faster."
    failed = failures(doc, resume)
    assert any(original[:30] in detail for detail in failed["Coverage"])
    assert any("dashboards ran faster" in detail for detail in failed["No additions"])


def test_reordered_bullets_fail(case):
    doc, resume = case
    resume.experience[0].bullets.reverse()
    assert failures(doc, resume) == {
        "Order": ["experience[0].bullets: bullets are not in source order"]
    }


def test_dropped_section_fails(case):
    doc, resume = case
    resume.education = []
    failed = failures(doc, resume)
    assert any("Bachelor of Technology" in detail for detail in failed["Coverage"])


def test_split_bullet_fails(case):
    doc, resume = case
    first, rest = resume.experience[0].bullets[0].split(",", 1)
    resume.experience[0].bullets[0:1] = [first + ".", rest.strip()]
    assert {"Coverage", "No additions"} <= set(failures(doc, resume))


def test_changed_date_fails(case):
    doc, resume = case
    resume.experience[0].start = "2021-01"
    failed = failures(doc, resume)
    assert failed["No additions"] == ["experience[0]: dates 2021-01 to present not in the source"]


def test_sidecar_tracks_the_verified_yaml(case, tmp_path):
    doc, resume = case
    yaml_path = tmp_path / "resume.yaml"
    dump_resume(resume, yaml_path)
    assert verification_state(yaml_path) == "unverified"
    results = verify(doc, resume, CONFIG)
    write_sidecar(yaml_path, Path("source"), results)
    assert passed(results) and verification_state(yaml_path) == "passed"
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8") + "# my note\n", encoding="utf-8")
    assert verification_state(yaml_path) == "edited"


@pytest.mark.parametrize("name", ["career_ops.html", "moderncv.tex"])
def test_run_command_end_to_end(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(FIXTURES / name)])
    assert result.exit_code == 0, result.output
    out = tmp_path / "out" / Path(name).stem
    produced = {path.name for path in out.iterdir()}
    assert produced == {
        "Jane_Doe_Resume.pdf",
        "Jane_Doe_Resume.docx",
        "Jane_Doe_Resume.txt",
        "Jane_Doe_Resume.md",
        "resume.yaml",
        "resume.yaml.verified",
        "report.json",
        "ats_view.txt",
    }
    assert "Faithfulness" in result.output and "ATS check" in result.output


def test_render_refuses_a_failed_verification_unless_forced(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = FIXTURES / "career_ops.html"
    yaml_path = tmp_path / "resume.yaml"
    assert runner.invoke(app, ["ingest", str(source), "-o", str(yaml_path)]).exit_code == 0

    # a hand edit after a pass is allowed, with a warning
    text = yaml_path.read_text(encoding="utf-8")
    yaml_path.write_text(text.replace("Senior Data Engineer", "Staff Data Engineer"), "utf-8")
    edited = runner.invoke(app, ["render", str(yaml_path), "--out", str(tmp_path / "pdf")])
    assert edited.exit_code == 0 and "edited after it passed" in edited.output

    # re-verifying that edit fails, and names the invented title
    failed = runner.invoke(app, ["verify", str(source), str(yaml_path)])
    assert failed.exit_code == 1 and "Staff Data Engineer" in failed.output
    refused = runner.invoke(app, ["render", str(yaml_path), "--out", str(tmp_path / "pdf")])
    assert refused.exit_code == 1 and "--force" in refused.output
    forced = runner.invoke(
        app, ["render", str(yaml_path), "--out", str(tmp_path / "pdf"), "--force"]
    )
    assert forced.exit_code == 0


def test_unsupported_input_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cv.docx").write_bytes(b"PK")
    assert runner.invoke(app, ["ingest", "cv.docx"]).exit_code == 2
    assert runner.invoke(app, ["ingest", "missing.html"]).exit_code == 2


def test_identical_lines_in_one_list_are_not_a_reordering(case):
    doc, resume = case
    resume.extra_sections.append(
        type(resume.extra_sections[0])(title="Core Competencies", items=["CI/CD Automation"])
    )
    twin = [b for b in doc.blocks if b.kind == "bullet"][0]
    doc.blocks += [twin, type(twin)("bullet", "Something else entirely."), twin]
    resume.extra_sections[-1].items = [twin.text, "Something else entirely.", twin.text]
    assert "Order" not in failures(doc, resume)
