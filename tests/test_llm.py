from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.config import Config
from cvforge.extract.llm import INSTRUCTIONS, extract_llm, source_prompt
from cvforge.extract.rules import extract
from cvforge.ingest import load_source
from cvforge.ingest.sourcedoc import split_dropped
from cvforge.models import Meta
from cvforge.verify import passed, verify

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "career_ops.html"
CONFIG = Config()
SKILL = Path(__file__).parents[1] / ".claude" / "skills" / "format-resume" / "SKILL.md"


class FakeClient:
    """Stands in for anthropic.Anthropic(): records the request, returns a canned answer."""

    def __init__(self, parsed, stop_reason="end_turn"):
        self.response = SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason)
        self.request: dict = {}
        self.messages = SimpleNamespace(parse=self.parse)

    def parse(self, **kwargs):
        self.request = kwargs
        return self.response


@pytest.fixture
def doc():
    return split_dropped(load_source(FIXTURE, CONFIG), CONFIG)[0]


def test_instructions_carry_the_spec_rules_verbatim():
    for rule in (
        "Map content into the schema only.",
        "Copy all text exactly.",
        "Do not paraphrase, fix grammar, shorten, merge, split, add, drop, or reorder bullets "
        "within an entry.",
        "You may normalize date formats.",
        "Put anything you are unsure about into `extra_sections`.",
    ):
        assert rule in INSTRUCTIONS
        assert rule.split(",")[0].rstrip(".") in " ".join(SKILL.read_text(encoding="utf-8").split())


def test_request_shape_and_result(doc):
    answer = extract(doc, CONFIG, Meta()).resume  # what a faithful model would return
    client = FakeClient(answer)
    meta = Meta(source_file="cv.html", source_tool="career-ops")
    extraction = extract_llm(doc, CONFIG, meta, client=client)

    request = client.request
    assert request["model"] == CONFIG.llm_model == "claude-opus-5-5"
    assert request["system"] == INSTRUCTIONS
    assert request["output_format"].__name__ == "Resume"
    assert "tool_choice" not in request and "thinking" not in request
    prompt = request["messages"][0]["content"]
    assert "[line/org] Example Corp" in prompt
    assert "- linkedin.com/in/jane-doe -> https://linkedin.com/in/jane-doe-a1b2c3" in prompt

    assert extraction.resume.meta == meta  # meta is ours, never the model's
    assert passed(verify(doc, extraction.resume, CONFIG))


def test_a_paraphrasing_model_is_caught_by_verify(doc):
    answer = extract(doc, CONFIG, Meta()).resume
    answer.experience[0].bullets[0] = "Designed fast data pipelines that halved latency."
    extraction = extract_llm(doc, CONFIG, Meta(), client=FakeClient(answer))
    assert not passed(verify(doc, extraction.resume, CONFIG))


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_incomplete_answer_is_an_error(doc, stop_reason):
    with pytest.raises(RuntimeError, match=stop_reason):
        extract_llm(doc, CONFIG, Meta(), client=FakeClient(None, stop_reason))


def test_source_prompt_keeps_every_block(doc):
    prompt = source_prompt(doc)
    assert all(block.text in prompt for block in doc.blocks)


def test_cli_reports_a_failed_anthropic_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))  # no stored login either
    result = runner.invoke(app, ["ingest", str(FIXTURE), "--extractor", "anthropic"])
    assert result.exit_code == 2
    assert "anthropic extractor" in result.output
    assert not (tmp_path / "out").exists()  # nothing written when extraction fails
    assert runner.invoke(app, ["ingest", str(FIXTURE), "--extractor", "gpt"]).exit_code == 2
