from pathlib import Path

import pytest

from cvforge.config import Config, load_config
from cvforge.dates import find_date_ranges, parse_date_range
from cvforge.extract.rules import extract
from cvforge.ingest import detect_type, load_source
from cvforge.ingest.html import parse_html
from cvforge.ingest.latex import parse_latex
from cvforge.ingest.sourcedoc import Block, split_dropped
from cvforge.models import Meta
from cvforge.verify import passed, verify
from cvforge.yaml_io import load_resume

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = Config()


def ingest(name: str, config: Config = CONFIG):
    doc, dropped = split_dropped(load_source(FIXTURES / name, config), config)
    meta = Meta(source_file=f"tests/fixtures/{name}", source_tool="other")
    return doc, dropped, extract(doc, config, meta)


@pytest.mark.parametrize("name", ["career_ops.html", "moderncv.tex"])
def test_fixture_ingests_to_expected_yaml(name):
    doc, _, extraction = ingest(name)
    expected = load_resume((FIXTURES / name).with_suffix(".expected.yaml"))
    assert extraction.resume == expected
    assert passed(verify(doc, extraction.resume, CONFIG))


def test_html_ignores_markup_that_is_not_content():
    doc, _, extraction = ingest("career_ops.html")
    text = doc.raw_text
    for noise in ("HEADER", "not content", "internal template note", "font-weight", "|"):
        assert noise not in text
    assert extraction.unplaced == []
    # <strong> becomes **bold**; literal ** in the source is kept as it is
    assert "**PySpark** and Jenkins, reducing latency by **50%**." in text


def test_html_link_keeps_short_text_and_full_target():
    resume = ingest("career_ops.html")[2].resume
    linkedin, github = resume.basics.links
    assert (linkedin.text, linkedin.url) == (
        "linkedin.com/in/jane-doe",
        "https://linkedin.com/in/jane-doe-a1b2c3",
    )
    assert github.text is None  # the visible text already is the URL
    assert resume.projects[0].url == "https://github.com/janedoe/tf-modules"


def test_latex_conversions():
    doc, dropped, extraction = ingest("moderncv.tex")
    text = doc.raw_text
    assert "40%" in text and "Jenkins & GitHub Actions" in text
    assert "Terraform – the most" in text  # -- becomes an en dash
    assert "ignored" not in text and "vspace" not in text and "1pt" not in text
    assert dropped == ["heading: References", "bullet: Available upon request."]
    assert extraction.unplaced == [
        "Languages: English (professional working proficiency), Marathi (spoken)."
    ]
    resume = extraction.resume
    assert resume.basics.phone == "+91 90000 00000"  # not the [mobile] option
    assert [link.label for link in resume.basics.links] == ["LinkedIn", "GitHub"]
    assert (resume.education[0].start, resume.education[0].end) == ("2018", "2022")
    project = resume.projects[0]
    assert (project.name, project.url) == (
        "LakehouseLab",
        "https://github.com/janedoe/lakehouse-lab",
    )
    assert project.description.startswith("(2026, personal): lakehouse")


def test_a_new_latex_template_needs_only_config(tmp_path):
    toml = tmp_path / "cvforge.toml"
    toml.write_text(
        '[latex_macros]\nresumeSubheading = ["org", "location", "title", "dates"]\n'
        'resumeItem = ["body"]\n',
        encoding="utf-8",
    )
    config = load_config(toml)
    assert "cventry" in config.latex_macros  # the file adds to the defaults
    source = r"""\begin{document}
\section{Experience}
\resumeSubheading{Acme \& Sons}{Pune, India}{Engineer}{Jan 2020 -- Mar 2021}
\begin{itemize}
  \item Shipped \textbf{C\#} services for 3 teams.
\end{itemize}
\end{document}"""
    doc = parse_latex(source, config)
    doc.blocks.insert(0, Block("line", "Jane Doe", role="name"))  # the snippet has no \name
    job = extract(doc, config, Meta()).resume.experience[0]
    assert (job.company, job.title, job.location) == ("Acme & Sons", "Engineer", "Pune, India")
    assert (job.start, job.end) == ("2020-01", "2021-03")
    assert job.bullets == ["Shipped **C#** services for 3 teams."]


def test_html_without_known_classes_loses_nothing():
    source = """<html><body><h1>Jane Doe</h1>
    <h2>Experience</h2><p>Acme, Engineer, 2020 to 2021</p><ul><li>Built things.</li></ul>
    <h2>Hobbies</h2><p>Chess &amp; <b>trail</b> running</p></body></html>"""
    doc = parse_html(source, CONFIG)
    extraction = extract(doc, CONFIG, Meta())
    resume = extraction.resume
    assert resume.basics.name == "Jane Doe"
    assert extraction.unplaced == [
        "Experience: Acme, Engineer, 2020 to 2021",
        "Experience: Built things.",
    ]
    assert {s.title: s.items for s in resume.extra_sections} == {
        "Experience": ["Acme, Engineer, 2020 to 2021", "Built things."],
        "Hobbies": ["Chess & **trail** running"],
    }
    assert passed(verify(doc, resume, CONFIG))


def test_detect_type_by_extension_then_content(tmp_path):
    assert detect_type(Path("cv.HTML"), "") == "html"
    assert detect_type(Path("cv.txt"), "\\documentclass{article}") == "text"
    assert detect_type(Path("cv"), "\\documentclass{article}") == "latex"
    assert detect_type(Path("cv"), '{"basics": {}}') == "jsonresume"
    assert detect_type(Path("cv"), "# Jane Doe") == "markdown"
    assert detect_type(Path("cv"), "  <!DOCTYPE html><html>") == "html"
    with pytest.raises(ValueError, match="unsupported input type"):
        detect_type(Path("cv.docx"), "PK")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Apr 2024 - Present", ("2024-04", "present")),
        ("Aug 2022 – Apr 2024", ("2022-08", "2024-04")),
        ("September 2019 to June 2021", ("2019-09", "2021-06")),
        ("2018-2022", ("2018", "2022")),
        ("03/2020 - 11/2021", ("2020-03", "2021-11")),
        ("2022", ("2022", None)),
        ("Feb 2022", ("2022-02", None)),
        ("Pune, India", None),
        ("154 tables in 2022 and more", None),
    ],
)
def test_parse_date_range(text, expected):
    assert parse_date_range(text) == expected


def test_dates_inside_prose_are_found_but_numbers_are_not():
    found = [pair for pair, _ in find_date_ranges("Promoted in Apr 2026 after 5,000+ rows, 2024.")]
    assert found == [("2026-04", None), ("2024", None)]
