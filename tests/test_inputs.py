import json
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.config import Config, resource
from cvforge.export import to_jsonresume
from cvforge.extract.rules import extract
from cvforge.ingest import load_source
from cvforge.ingest.sourcedoc import split_dropped
from cvforge.models import Meta
from cvforge.render.text_renderer import render_text
from cvforge.render.typst_renderer import render_pdf
from cvforge.render.view import build_view
from cvforge.verify import verify
from cvforge.watch import find_sources, watch
from cvforge.yaml_io import load_resume

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = resource("examples/resume.yaml")
CONFIG = Config()


def ingest(path: Path):
    """(source doc, extraction) with the rules extractor; asserts the result is faithful."""
    doc, _ = split_dropped(load_source(path, CONFIG), CONFIG)
    extraction = extract(doc, CONFIG, Meta(source_file=path.name, source_tool="other"))
    failed = [r for r in verify(doc, extraction.resume, CONFIG) if r.status == "fail"]
    assert not failed, [r.details for r in failed]
    return doc, extraction


def test_markdown_fixture_ingests_to_expected_yaml():
    _, extraction = ingest(FIXTURES / "resume.md")
    expected = load_resume(FIXTURES / "resume.expected.yaml")
    expected.meta.source_file = "resume.md"
    assert extraction.resume == expected
    assert extraction.unplaced == []
    resume = extraction.resume
    assert [job.title for job in resume.experience] == [
        "Senior Data Engineer",
        "Data Engineer",  # second role under one company line
        "Associate Data Engineer",
    ]
    assert resume.experience[1].company == "Example Corp"
    assert resume.basics.links[0].text == "linkedin.com/in/jane-doe"
    assert resume.projects[0].tech == ["PySpark", "Delta Lake", "dbt"]


def test_cvforge_markdown_output_reads_back_as_the_same_resume(tmp_path):
    original = load_resume(EXAMPLE)
    path = tmp_path / "resume.md"
    path.write_text(render_text(build_view(original, CONFIG), markdown=True), encoding="utf-8")
    _, extraction = ingest(path)
    resume = extraction.resume
    assert resume.basics.name == original.basics.name
    assert resume.basics.headline == original.basics.headline
    assert resume.summary == original.summary
    assert resume.skills == original.skills
    assert [(j.company, j.title, j.start, j.end, j.bullets) for j in resume.experience] == [
        (j.company, j.title, j.start, j.end, j.bullets) for j in original.experience
    ]
    assert resume.projects[0].name == "lakehouse-lab" and resume.projects[0].url


def test_json_resume_round_trip(tmp_path):
    original = load_resume(EXAMPLE)
    path = tmp_path / "resume.json"
    path.write_text(json.dumps(to_jsonresume(original)), encoding="utf-8")
    _, extraction = ingest(path)
    resume = extraction.resume
    assert resume.basics.headline == "Senior Data Engineer"
    assert resume.basics.email == original.basics.email
    assert [link.label for link in resume.basics.links] == ["LinkedIn", "GitHub"]
    assert resume.skills == original.skills
    assert [(j.company, j.title, j.location, j.start, j.end) for j in resume.experience] == [
        (j.company, j.title, j.location, j.start, j.end) for j in original.experience
    ]
    assert resume.education[0].field == "Computer Science"
    assert resume.certifications[0].issuer == "Snowflake"
    assert [(x.language, x.fluency) for x in resume.languages] == [
        (x.language, x.fluency) for x in original.languages
    ]
    assert resume.projects[0].tech == ["PySpark", "Delta Lake", "dbt"]


def test_json_resume_keeps_sections_it_has_no_field_for(tmp_path):
    path = tmp_path / "resume.json"
    data = {
        "basics": {"name": "Jane Doe", "location": {"city": "Pune", "countryCode": "IN"}},
        "work": [{"name": "Acme", "position": "Engineer", "startDate": "2020-01-15"}],
        "interests": [{"name": "Chess", "keywords": ["Openings", "Endgames"]}],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    resume = ingest(path)[1].resume
    assert resume.basics.location == "Pune, IN"
    assert (resume.experience[0].start, resume.experience[0].end) == ("2020-01", "present")
    assert resume.extra_sections[0].title == "Interests"
    assert resume.extra_sections[0].items == ["Chess, Openings, Endgames"]


def test_plain_text_keeps_everything_even_without_structure(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text(render_text(build_view(load_resume(EXAMPLE), CONFIG)), encoding="utf-8")
    doc, extraction = ingest(path)
    resume = extraction.resume
    assert resume.basics.name == "Jane Doe"
    assert resume.basics.email == "jane@example.com" and resume.basics.phone == "+91 90000 00000"
    assert resume.basics.links[0].url == "https://linkedin.com/in/janedoe"
    assert resume.skills[0].items == ["Python", "SQL", "Bash"]
    # entries have no markup to map from: they are kept as lines and reported
    assert any(item.startswith("EXPERIENCE: Example Corp") for item in extraction.unplaced)
    assert [b.text for b in doc.blocks if b.kind == "heading"][:3] == [
        "SUMMARY",
        "SKILLS",
        "EXPERIENCE",
    ]


def test_pdf_fallback_recovers_text_and_warns(tmp_path, monkeypatch):
    pdf = tmp_path / "resume.pdf"
    render_pdf(build_view(load_resume(EXAMPLE), CONFIG), "classic", "a4", pdf)
    _, extraction = ingest(pdf)
    assert extraction.resume.basics.name == "Jane Doe"
    assert extraction.resume.basics.email == "jane@example.com"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["ingest", str(pdf)])
    assert result.exit_code == 0, result.output
    assert "structure may be lost" in result.output


def test_unsupported_and_binary_inputs_are_usage_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cv.docx").write_bytes(b"PK\x03\x04\xff\xfe")
    (tmp_path / "cv.txt").write_bytes(b"\xff\xfe\x00binary")
    assert runner.invoke(app, ["ingest", "cv.docx"]).exit_code == 2
    assert runner.invoke(app, ["ingest", "cv.txt"]).exit_code == 2


def test_batch_runs_every_source_and_reports_failures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inbox = tmp_path / "inbox"
    (inbox / "nested").mkdir(parents=True)
    (inbox / "a.html").write_bytes((FIXTURES / "career_ops.html").read_bytes())
    (inbox / "nested" / "b.tex").write_bytes((FIXTURES / "moderncv.tex").read_bytes())
    (inbox / "notes.md").write_text("# not a batch input\n", encoding="utf-8")
    assert [p.name for p in find_sources(inbox)] == ["a.html", "b.tex"]

    ok = runner.invoke(app, ["batch", str(inbox)])
    assert ok.exit_code == 0, ok.output
    assert (tmp_path / "out" / "a" / "Jane_Doe_Resume.pdf").exists()
    assert (tmp_path / "out" / "b" / "Jane_Doe_Resume.docx").exists()

    (inbox / "broken.html").write_text("<html><body><p>no name</p></body></html>", "utf-8")
    failed = runner.invoke(app, ["batch", str(inbox)])
    assert failed.exit_code == 1
    summary = failed.output.split("batch summary")[1]
    assert summary.count("ok  ") == 2 and "failed (exit 2)" in summary and "broken.html" in summary
    assert runner.invoke(app, ["batch", str(tmp_path / "empty")]).exit_code == 2


def test_watch_picks_up_new_and_changed_files_only(tmp_path):
    existing = tmp_path / "already-here.html"
    existing.write_text("<html></html>", encoding="utf-8")
    handled: list[str] = []
    stop = threading.Event()
    done = threading.Event()

    def handle(path: Path) -> None:
        handled.append(path.name)
        if len(handled) == 2:
            done.set()

    thread = threading.Thread(target=watch, args=([tmp_path], handle, stop, 0.05))
    thread.start()
    try:
        (tmp_path / "ignored.md").write_text("# no", encoding="utf-8")
        (tmp_path / "new.tex").write_text("\\documentclass{article}", encoding="utf-8")
        stop.wait(0.5)
        existing.write_text("<html><body>changed</body></html>", encoding="utf-8")
        assert done.wait(10), handled
    finally:
        stop.set()
        thread.join(5)
    assert sorted(handled) == ["already-here.html", "new.tex"]


def test_watch_command_needs_folders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["watch"]).exit_code == 2
    assert runner.invoke(app, ["watch", "no-such-folder"]).exit_code == 2


@pytest.mark.parametrize("name", ["resume.md"])
def test_run_accepts_markdown(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["run", str(FIXTURES / name)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "resume" / "Jane_Doe_Resume.pdf").exists()
