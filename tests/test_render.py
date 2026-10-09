import tomllib

import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from cvforge.cli import app, output_stem
from cvforge.config import Config, resource
from cvforge.models import Resume
from cvforge.render.segments import to_segments
from cvforge.render.typst_renderer import load_theme, render_pdf
from cvforge.render.view import build_view, date_range, display_url
from cvforge.yaml_io import load_resume

runner = CliRunner()
EXAMPLE = resource("examples/resume.yaml")
NASTY = "C# & F# cost $5 < $9 > 1% of {x} \\ `code` a_b @home #42 * 2 [link] ~tilde ^hat"


def pdf_text(path) -> str:
    return " ".join(" ".join(page.extract_text() for page in PdfReader(path).pages).split())


def render(resume: Resume, tmp_path, theme: str = "classic"):
    out = tmp_path / "resume.pdf"
    render_pdf(build_view(resume, Config()), theme, "a4", out)
    return out


def test_to_segments():
    assert to_segments("a **b** c") == [
        {"text": "a ", "bold": False},
        {"text": "b", "bold": True},
        {"text": " c", "bold": False},
    ]
    assert to_segments("**all**") == [{"text": "all", "bold": True}]
    assert to_segments("2 * 3 * 4") == [{"text": "2 * 3 * 4", "bold": False}]


def test_dates_and_urls():
    assert date_range("2023-06", "present", "%b %Y") == "Jun 2023 – Present"
    assert date_range("2015", "2019", "%b %Y") == "2015 – 2019"
    assert date_range(None, "2022", "%b %Y") == "2022"
    assert display_url("https://linkedin.com/in/janedoe/") == "linkedin.com/in/janedoe"


def test_consecutive_roles_share_one_company_line():
    view = build_view(load_resume(EXAMPLE), Config())
    experience = next(s for s in view["sections"] if s["heading"] == "Experience")
    lines = [[line["style"] for line in block["lines"]] for block in experience["blocks"]]
    assert lines == [["primary", "secondary"], ["secondary"], ["primary", "secondary"]]
    assert [s["heading"] for s in view["sections"]][:5] == [
        "Summary",
        "Skills",
        "Experience",
        "Projects",
        "Education",
    ]


def test_render_command_writes_pdf(tmp_path):
    result = runner.invoke(app, ["render", str(EXAMPLE), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    pdf = tmp_path / "Jane_Doe_Resume.pdf"
    reader = PdfReader(pdf)
    text = pdf_text(pdf)
    assert text.startswith("Jane Doe")
    assert reader.metadata.title == "Jane Doe Resume"
    assert reader.pages[0].mediabox.width == pytest.approx(595.28, abs=0.1)  # A4
    # hyphenation and ligatures are off: these words survive intact, with no ligature glyphs
    for word in ("efficient", "workflow", "Kubernetes", "PySpark", "₹12L", "Jun 2023 – Present"):
        assert word in text
    assert not set(text) & set("ﬁﬂﬀﬃﬄ�")
    lines = [ln.strip() for page in reader.pages for ln in page.extract_text().splitlines()]
    assert not [
        ln for ln in lines if ln.endswith(("-", "/"))
    ]  # "on-call" is not split at its hyphen
    # only the bundled font is used: no glyph fell back to another family
    fonts = {f["/BaseFont"] for page in reader.pages for f in _fonts(page)}
    assert fonts and all("SourceSerif4" in name for name in fonts)


def _fonts(page):
    return [font.get_object() for font in page["/Resources"]["/Font"].values()]


def test_special_characters_render_verbatim(tmp_path):
    resume = Resume.model_validate(
        {
            "basics": {"name": "Jane O'Doe", "headline": NASTY, "email": "j_d+x@example.com"},
            "summary": f"**{NASTY}** then plain {NASTY}",
            "skills": [{"category": "C# & $", "items": ["#hash", "$dollar", "*star*", "_under_"]}],
            "experience": [
                {
                    "company": "A < B > C & Co. #1",
                    "title": "@Lead_Dev",
                    "bullets": [NASTY, "= + - / 1."],
                }
            ],
            "extra_sections": [{"title": "Misc & More", "items": ["#set text(red)", "$ x^2 $"]}],
        }
    )
    text = pdf_text(render(resume, tmp_path))
    for expected in (
        NASTY,
        "A < B > C & Co. #1",
        "@Lead_Dev",
        "C# & $:",
        "#hash, $dollar, *star*, _under_",
        "#set text(red)",
        "$ x^2 $",
        "= + - / 1.",
        "j_d+x@example.com",
    ):
        assert expected in text, expected
    assert text.count(NASTY) == 4  # headline, bold summary, plain summary, bullet


def test_unknown_theme_is_usage_error(tmp_path):
    result = runner.invoke(app, ["render", str(EXAMPLE), "--theme", "nope", "--out", str(tmp_path)])
    assert result.exit_code == 2


def test_invalid_yaml_is_usage_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("basics: {}\n", encoding="utf-8")
    assert runner.invoke(app, ["render", str(bad)]).exit_code == 2


def test_output_stem():
    resume = Resume.model_validate(
        {"basics": {"name": "Jane O'Doe"}, "meta": {"target_company": "Acme Inc."}}
    )
    assert output_stem(resume, Config()) == "Jane_ODoe_Resume"
    assert output_stem(resume, Config(company_suffix=True)) == "Jane_ODoe_Resume_Acme_Inc"


@pytest.mark.parametrize("theme", ["classic", "modern", "compact"])
def test_theme_tokens_within_spec_ranges(theme):
    t = load_theme(theme)
    assert 22 <= t["name_size"] <= 26
    assert 11 <= t["headline_size"] <= 12
    assert 10.5 <= t["heading_size"] <= 11.5
    assert 0.06 <= t["heading_tracking"] <= 0.1
    assert 10 <= t["body_size"] <= 10.5
    assert 1.2 <= t["line_height"] <= 1.3
    assert 10 <= t["section_gap"] <= 12
    assert 6 <= t["entry_gap"] <= 8
    assert 14 <= t["margin"] <= 18
    assert _contrast_on_white(t["muted"]) >= 4.5
    assert _contrast_on_white(t["accent"]) >= 4.5  # also the contrast of white text on a band


def _contrast_on_white(hex_color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    return 1.05 / (luminance + 0.05)


def test_example_config_matches_defaults():
    example = tomllib.loads(resource("cvforge.toml.example").read_text(encoding="utf-8"))
    assert Config.model_validate(example) == Config()


def test_extra_sections_render_after_their_anchor_and_tags_go_inline():
    resume = Resume.model_validate(
        {
            "basics": {"name": "Jane Doe"},
            "summary": "A summary.",
            "skills": [{"category": "Languages", "items": ["Python"]}],
            "extra_sections": [
                {"title": "Core Competencies", "after": "summary", "items": ["CI/CD", "Snowflake"]},
                {"title": "Volunteering", "items": ["Taught a SQL workshop for 120 students."]},
                {"title": "Talks", "after": "awards", "items": ["One talk", "**Bold** talk"]},
            ],
        }
    )
    sections = build_view(resume, Config())["sections"]
    assert [s["heading"] for s in sections] == [
        "Summary",
        "Core Competencies",
        "Skills",
        "Talks",  # its anchor section is empty, but it keeps that position
        "Volunteering",  # no anchor: at the extra_sections slot
    ]
    kinds = {s["heading"]: s["blocks"][0]["kind"] for s in sections}
    assert kinds["Core Competencies"] == "inline"  # short tags share one line
    assert kinds["Volunteering"] == "bullets"  # a single sentence stays a bullet
    assert kinds["Talks"] == "bullets"  # bold text is not a plain tag
