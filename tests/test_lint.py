from typer.testing import CliRunner

from cvforge.cli import app
from cvforge.config import resource
from cvforge.lint import lint
from cvforge.models import Resume
from cvforge.yaml_io import load_resume

runner = CliRunner()
EXAMPLE = resource("examples/resume.yaml")


def rules(resume: dict) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for warning in lint(Resume.model_validate({"basics": {"name": "Jane Doe"}, **resume})):
        found.setdefault(warning.rule, []).append(warning.location)
    return found


def job(bullets=(), start="2020-01", end="2021-01", company="Acme") -> dict:
    return {
        "company": company,
        "title": "Engineer",
        "start": start,
        "end": end,
        "bullets": list(bullets),
    }


def test_example_resume_is_clean():
    assert lint(load_resume(EXAMPLE)) == []


def test_bullet_rules():
    found = rules(
        {
            "experience": [
                job(
                    [
                        "Shipped " + "x" * 220,
                        "Responsible for the nightly load.",
                        "Reduced costs after I rewrote my loader.",
                        "Manages the ingestion platform.",
                        "Building dashboards for finance.",
                    ]
                )
            ]
        }
    )
    assert found["long-bullet"] == ["experience[0].bullets[0]"]
    assert found["weak-start"] == ["experience[0].bullets[1]"]
    assert found["first-person"] == ["experience[0].bullets[2]"]
    assert found["tense"] == ["experience[0].bullets[3]", "experience[0].bullets[4]"]


def test_present_tense_is_fine_in_a_current_role():
    assert "tense" not in rules({"experience": [job(["Manages the platform."], end="present")]})


def test_keyword_repeat_and_many_skills():
    found = rules(
        {
            "experience": [job([f"Moved feed {n} to AWS overnight." for n in "abcd"])],
            "skills": [{"category": "All", "items": [f"skill{n}" for n in range(36)]}],
        }
    )
    assert found["keyword-repeat"] == ["bullets"]
    assert found["many-skills"] == ["skills"]


def test_duplicate_bullets_across_entries():
    bullet = "Cut the nightly Redshift load from four hours to forty minutes."
    found = rules(
        {
            "experience": [
                job([bullet]),
                job([bullet.replace("Cut", "Reduced")], "2018-01", "2019-12"),
            ]
        }
    )
    assert found["duplicate-bullet"] == ["experience[0].bullets[0] and experience[1].bullets[0]"]


def test_date_rules():
    found = rules(
        {
            "experience": [
                job(start="2021-03", end="present"),
                job(start="2020-01", end="2021-06"),  # overlaps the first
                job(start="2019", end="2019"),  # mixed format
                {"company": "Acme", "title": "Intern"},  # no dates
            ],
            "education": [{"institution": "Example Institute"}],
        }
    )
    assert found["overlapping-dates"] == ["experience[0] and experience[1]"]
    assert found["mixed-dates"] == ["experience"]
    assert found["missing-date"] == ["experience[3]", "education[0]"]


def test_promotion_in_the_same_month_is_not_an_overlap():
    found = rules({"experience": [job(start="2024-04", end="present"), job(end="2024-04")]})
    assert "overlapping-dates" not in found


def test_summary_rules():
    found = rules({"summary": "I build pipelines. " + "x" * 420})
    assert set(found) == {"first-person", "long-summary"}


def test_lint_command_never_fails(tmp_path):
    path = tmp_path / "resume.yaml"
    path.write_text(
        "basics:\n  name: Jane Doe\nexperience:\n  - company: Acme\n    title: Engineer\n"
        "    bullets:\n      - Responsible for everything.\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["lint", str(path)])
    assert result.exit_code == 0
    assert "weak-start" in result.output and "experience[0].bullets[0]" in result.output
