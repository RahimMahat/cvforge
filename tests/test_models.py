import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.config import Config, load_config, resource
from cvforge.models import Resume
from cvforge.yaml_io import dump_resume, dump_yaml, load_resume, load_yaml

runner = CliRunner()
EXAMPLE = resource("examples/resume.yaml")


def minimal(**overrides) -> dict:
    return {"basics": {"name": "Jane Doe"}, **overrides}


def job(**overrides) -> dict:
    return {"company": "Acme", "title": "Engineer", **overrides}


def test_schema_command_prints_json_schema():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    schema = json.loads(result.stdout)
    assert schema["type"] == "object"
    assert {"basics", "experience", "extra_sections"} <= set(schema["properties"])
    assert schema["required"] == ["basics"]


def test_example_resume_validates():
    resume = load_resume(EXAMPLE)
    assert resume.basics.name == "Jane Doe"
    assert resume.experience[0].start == "2023-06"
    assert resume.experience[0].end == "present"
    assert resume.education[0].start == "2015"  # bare YAML int is coerced


@pytest.mark.parametrize("date", ["2023-13", "2023-6", "June 2023", "23", "Present", ""])
def test_bad_dates_rejected(date):
    with pytest.raises(ValidationError):
        Resume.model_validate(minimal(experience=[job(start=date)]))


@pytest.mark.parametrize(
    "text",
    ["Built <b>pipelines</b>", "Built \\textbf{pipelines}", "Built **pipelines", "a<br/>b"],
)
def test_non_bold_markup_rejected(text):
    with pytest.raises(ValidationError):
        Resume.model_validate(minimal(experience=[job(bullets=[text])]))


def test_literal_symbols_allowed():
    text = "C# & **F#** cost $5 < $9 > 1% of {x} \\ `code` a_b @home #42 * 2"
    resume = Resume.model_validate(minimal(experience=[job(bullets=[text])]))
    assert resume.experience[0].bullets == [text]


def test_unknown_keys_rejected():
    with pytest.raises(ValidationError):
        Resume.model_validate(minimal(hobbies=["chess"]))


def test_yaml_round_trip_keeps_comments_and_order(tmp_path):
    src = tmp_path / "in.yaml"
    src.write_text("# my note\nbasics:\n  name: Jane Doe # inline\nsummary: Hi\n", encoding="utf-8")
    out = tmp_path / "out.yaml"
    dump_yaml(load_yaml(src), out)
    assert out.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_dump_resume_round_trips_and_omits_empty(tmp_path):
    resume = load_resume(EXAMPLE)
    out = tmp_path / "resume.yaml"
    dump_resume(resume, out)
    assert load_resume(out) == resume
    assert "awards" not in out.read_text(encoding="utf-8")


def test_init_creates_files_and_refuses_overwrite(tmp_path):
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    assert load_resume(tmp_path / "resume.yaml").basics.name == "Jane Doe"
    assert load_config(tmp_path / "cvforge.toml") == Config()  # example documents the defaults
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 2
    assert runner.invoke(app, ["init", str(tmp_path), "--force"]).exit_code == 0


def test_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "cvforge.toml"
    path.write_text('them = "classic"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)
