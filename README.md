# cvforge

Deterministic, ATS-safe resume formatter. Takes resume content (career-ops HTML,
ai-job-search LaTeX, Markdown, JSON Resume, plain text), maps it to a hand-editable
`resume.yaml`, and typesets it without changing a word.

Spec: [cvforge-build-prompt.md](cvforge-build-prompt.md).

## Usage

```
uv sync
uv run cvforge init      # creates cvforge.toml and an example resume.yaml
uv run cvforge schema    # prints the JSON Schema of resume.yaml
uv run cvforge render examples/resume.yaml   # writes out/resume/Jane_Doe_Resume.pdf, then checks it
uv run cvforge check <pdf> --yaml resume.yaml [--jd jd.txt]   # what an ATS parser would see
uv run cvforge lint resume.yaml              # style warnings only, nothing is changed
```

`render` and `check` write `ats_view.txt` (the extracted text) and `report.json` beside the PDF
and exit 1 if any check fails.

## Development

```
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

`samples/` and `out/` hold personal data and are gitignored.

Bundled fonts in `fonts/` are under the SIL Open Font License; each family's folder holds its license.
