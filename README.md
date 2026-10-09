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
```

## Development

```
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

`samples/` and `out/` hold personal data and are gitignored.
