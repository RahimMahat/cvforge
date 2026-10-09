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
uv run cvforge run cv.html                   # everyday: ingest, verify, lint, render, check
uv run cvforge ingest cv.tex [-o resume.yaml]  # source -> resume.yaml, then verify
uv run cvforge verify cv.tex resume.yaml      # prove the YAML says what the source says
uv run cvforge render examples/resume.yaml   # writes out/resume/Jane_Doe_Resume.pdf, then checks it
uv run cvforge check <pdf> --yaml resume.yaml [--jd jd.txt]   # what an ATS parser would see
uv run cvforge lint resume.yaml              # style warnings only, nothing is changed
```

Everything for one source lands in `out/<source-stem>/`: the resume as PDF, DOCX, TXT and
Markdown, plus `resume.yaml`, `report.json` and `ats_view.txt`. Choose formats with
`--formats pdf,docx` or `formats` in `cvforge.toml`. `render` refuses a YAML whose
verification failed (override with `--force`); hand edits after a pass only warn.

`render` and `check` write `ats_view.txt` (the extracted text) and `report.json` beside the PDF
and exit 1 if any check fails.

## Headings

Section headings are rendered as standard words (Summary, Skills, Experience, ...), which is
what parsers look for. `resume.yaml` still records the source's own wording under
`meta.headings`; set `keep_heading_text = true` in `cvforge.toml` to render that instead
("Work Experience", "Technical Contributions"). The ATS check then flags them as non-standard.

## Inputs

| Input | How much structure is recovered |
|---|---|
| `.html` (career-ops), `.tex` (ai-job-search) | Everything, via the class and macro maps in config. |
| `.json` (JSON Resume) | Everything; sections with no cvforge field become extra sections. |
| `.md` | Headings, bullets, skills lines, and entries written as below. |
| `.txt`, `.pdf` | Name, contact line, headings, bullets and skills lines. Entries are kept as plain lines and reported; PDF is a last resort. |

Markdown entries use the same shape cvforge's own `.md` output has:

```
**Example Corp** | Pune, India
*Senior Data Engineer* | Jun 2023 – Present
- A bullet.
```

## Many files

```
uv run cvforge batch samples/          # every .html and .tex under a folder; exit 1 if any fail
uv run cvforge watch inbox/ other/     # process files as they appear or change (Ctrl+C stops)
uv run cvforge export resume.yaml --format jsonresume [-o resume.json]
```

`watch` with no folders uses `watch_dirs` from `cvforge.toml`. Files already present when it
starts are left alone; use `batch` for those.

## Terminal UI

```
uv sync --extra tui
uv run cvforge tui samples/
```

Lists the `.html` and `.tex` resumes under a folder. Press Enter on one, then change the theme
or the page limit: each change re-runs the normal pipeline and shows the page count and every
faithfulness, ATS, page-fit and lint result. `r` runs again, `q` quits. Outputs land in
`out/<source-stem>/` as usual.

## Themes and page fitting

```
uv run cvforge themes --preview                    # lists themes, writes out/themes/<theme>-1.png
uv run cvforge run cv.html --theme modern --pages 1
```

- `classic` (default): serif, black, uppercase headings with a thin rule.
- `modern`: sans-serif, name on a full-width colour band, accent headings and bullets.
- `compact`: the classic look at the dense end of every range.

All themes are single column and share `themes/base.typ`; a theme is a `theme.toml` of tokens.
`--pages N` tightens spacing, then line height, body size and margins (in that order, within
fixed floors) until the resume fits. If it cannot fit, nothing is dropped: the command reports
how many lines over it is and exits 1.

## Extractors

- `rules` (default): deterministic, no network.
- Claude Code skill: ask Claude Code to "format this resume"; it runs the rules extractor, fixes
  the mapping by hand if verification fails, then renders (`.claude/skills/format-resume`).
- `anthropic` (optional): `uv sync --extra llm`, set `ANTHROPIC_API_KEY`, then
  `cvforge ingest cv.html --extractor anthropic`. The model comes from `llm_model` in
  `cvforge.toml`. Its output goes through the same verification as the rules extractor.

## Install as a command

```
uv tool install ".[tui]"            # puts cvforge on your PATH
uv tool install --reinstall ".[tui]"   # after pulling changes
```

## Development

```
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

`samples/` and `out/` hold personal data and are gitignored.

Bundled fonts in `fonts/` are under the SIL Open Font License; each family's folder holds its license.
