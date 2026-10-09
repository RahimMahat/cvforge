"""Mistakes and damaged files must produce a clear exit code 2, never a traceback."""

import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvforge.cli import app, output_stem
from cvforge.config import Config, resource
from cvforge.models import Resume
from cvforge.verify import verification_state

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = resource("examples/resume.yaml")


def invoke(*args: object):
    result = runner.invoke(app, [str(arg) for arg in args])
    # typer.Exit is expected; any other exception means the command crashed
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    return result


@pytest.mark.parametrize(
    "toml",
    [
        'them = "classic"\n',  # unknown key
        "theme = \n",  # not valid TOML
        'paper = "a5"\n',
        "pages = 0\n",
        'formats = ["pdf", "odt"]\n',
        'section_order = ["summary", "hobbies"]\n',
    ],
)
def test_a_broken_config_is_a_usage_error_in_every_command(toml, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cvforge.toml").write_text(toml, encoding="utf-8")
    source = FIXTURES / "career_ops.html"
    for command in (
        ["render", EXAMPLE],
        ["run", source],
        ["ingest", source],
        ["batch", FIXTURES],
        ["watch", tmp_path],  # must fail at once, not start watching
        ["themes"],
        ["tui", FIXTURES],
    ):
        result = invoke(*command)
        assert result.exit_code == 2, (command[0], result.output)
        assert "Cannot read cvforge.toml" in " ".join(result.output.split()), command[0]
    assert not (tmp_path / "out").exists()


def test_an_unknown_theme_in_the_config_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cvforge.toml").write_text('theme = "nope"\n', encoding="utf-8")
    result = invoke("render", EXAMPLE)
    assert result.exit_code == 2 and "Unknown theme" in result.output


@pytest.mark.parametrize(
    "name",
    ["Jane_Doe_Resume.pdf", "Jane_Doe_Resume.docx", "Jane_Doe_Resume.txt", "report.json"],
)
def test_an_output_file_that_cannot_be_overwritten_is_reported(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert invoke("render", EXAMPLE, "--out", "o").exit_code == 0
    target = tmp_path / "o" / name
    os.chmod(target, stat.S_IREAD)  # as when the file is open in Word or a PDF viewer
    try:
        result = invoke("render", EXAMPLE, "--out", "o")
    finally:
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
    assert result.exit_code == 2
    assert "open in another program" in " ".join(result.output.split())


def test_damaged_files_from_an_earlier_run_do_not_break_the_next(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = FIXTURES / "career_ops.html"
    assert invoke("run", source).exit_code == 0
    out = tmp_path / "out" / "career_ops"
    (out / "report.json").write_text("{not json", encoding="utf-8")
    (out / "resume.yaml.verified").write_text("[]", encoding="utf-8")
    assert verification_state(out / "resume.yaml") == "unverified"
    refused = invoke("render", out / "resume.yaml")
    assert refused.exit_code == 1 and "unverified" in refused.output
    assert invoke("run", source).exit_code == 0  # a fresh run repairs both
    assert verification_state(out / "resume.yaml") == "passed"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("fake.pdf", "this is not a pdf"),
        ("list.json", "[1, 2, 3]"),
        ("strings.json", '{"basics": {"name": "Jane Doe"}, "skills": ["Python", "SQL"]}'),
        ("basics.json", '{"basics": ["Jane Doe"], "work": "none"}'),
        ("bad.json", "{not json"),
        ("empty.html", ""),
        ("empty.tex", ""),
        ("empty.md", ""),
        ("empty.txt", "  \n\n"),
    ],
)
def test_unreadable_sources_are_usage_errors(name, content, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / name).write_text(content, encoding="utf-8")
    result = invoke("run", name)
    assert result.exit_code == 2, result.output
    assert "Cannot ingest" in result.output
    assert not list(tmp_path.glob("out/*/*.pdf"))


def test_check_on_a_file_that_is_not_a_pdf(tmp_path):
    fake = tmp_path / "notes.pdf"
    fake.write_text("plain text", encoding="utf-8")
    result = invoke("check", fake)
    assert result.exit_code == 2 and "not a readable PDF" in result.output


def test_json_resume_items_of_the_wrong_type_are_kept_as_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = '{"basics": {"name": "Jane Doe"}, "awards": ["Employee of the year 2021"]}'
    (tmp_path / "cv.json").write_text(data, encoding="utf-8")
    assert invoke("ingest", "cv.json").exit_code == 0
    assert "Employee of the year 2021" in (tmp_path / "out/cv/resume.yaml").read_text("utf-8")


def test_sections_missing_from_section_order_are_still_rendered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cvforge.toml").write_text(
        'section_order = ["experience", "summary"]\ndate_format = "%m/%Y"\n', encoding="utf-8"
    )
    result = invoke("render", EXAMPLE, "--out", "o")
    assert result.exit_code == 0, result.output
    seen = (tmp_path / "o" / "ats_view.txt").read_text(encoding="utf-8")
    headings = [line for line in seen.splitlines() if line.isupper() and len(line.split()) == 1]
    assert headings == [
        "EXPERIENCE",  # the two the config names, in its order
        "SUMMARY",
        "SKILLS",  # then everything else in the default order: nothing is hidden
        "PROJECTS",
        "EDUCATION",
        "CERTIFICATIONS",
        "LANGUAGES",
        "VOLUNTEERING",
    ]
    assert "06/2023 – Present" in seen


def test_output_names_keep_non_latin_letters_and_their_marks():
    def stem(name: str) -> str:
        return output_stem(Resume.model_validate({"basics": {"name": name}}), Config())

    assert stem("Zoë Müller-Łukasz") == "Zoë_MüllerŁukasz_Resume"
    assert stem("राहिम महत") == "राहिम_महत_Resume"
    assert stem("*** !!!") == "Resume"
    assert stem("Jane O'Doe / Jr.") == "Jane_ODoe_Jr_Resume"
