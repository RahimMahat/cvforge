# cvforge

Deterministic, ATS-safe resume formatter. It typesets a hand-editable `resume.yaml` as PDF,
DOCX, TXT and Markdown. You can write that file yourself, or have cvforge build it from another
tool's output (career-ops HTML, ai-job-search LaTeX, or Markdown, JSON Resume, plain text, PDF)
and prove nothing was changed on the way.

- **Content is never rewritten.** The tool restructures and typesets; a faithfulness check
  compares the YAML against the source and blocks rendering if anything was added, dropped,
  reworded or reordered.
- **Layout is deterministic.** The same YAML and theme give the same output. No LLM is involved
  in rendering.
- **ATS-first.** Single column, real text, standard headings, no tables or icons; every PDF is
  re-read by independent text extractors before it is called done.

The full specification is in [cvforge-build-prompt.md](cvforge-build-prompt.md).

## Install

```
uv sync                        # in a checkout: run commands as `uv run cvforge ...`
uv tool install ".[tui]"       # or put `cvforge` on your PATH (re-run with --reinstall after changes)
```

Python 3.12+. Optional extras: `tui` (terminal UI), `llm` (the `anthropic` extractor).
`python -m cvforge` is the same command.

## Quick start

There are two ways in. Both end at the same `resume.yaml` and the same outputs.

### From scratch: no existing resume needed

```
cvforge init                    # writes cvforge.toml and an example resume.yaml
# edit resume.yaml: replace the example content with your own
cvforge lint resume.yaml        # optional: style warnings on your wording
cvforge render resume.yaml      # PDF, DOCX, TXT and Markdown in out/resume/, then the ATS check
```

The example file shows every section; delete the ones you don't need (only `basics.name` is
required). `cvforge schema` prints the exact shape, and the [resume.yaml](#resumeyaml) section
below covers the rules. Re-run `render` after each edit, with `--theme` and `--pages` as you like.
A hand-written file has no source to be compared against, so the faithfulness check is skipped;
the ATS check on the PDF still runs every time.

### From another tool's file

```
cvforge run cv.html                          # ingest, verify, lint, render, check
cvforge run cv.tex --theme modern --pages 1
```

This builds `resume.yaml` for you and verifies it against the source. You can still edit it by
hand afterwards and re-run `cvforge render out/<source-stem>/resume.yaml`.

### What you get

Everything lands in `out/<source-stem>/` (for a hand-written file, `out/<yaml-name>/`):

| File | What it is |
|---|---|
| `<First>_<Last>_Resume.pdf` / `.docx` / `.txt` / `.md` | The resume in each format. |
| `resume.yaml` | The content: the single source of truth, safe to edit by hand. |
| `resume.yaml.verified` | Records that this exact YAML passed verification. |
| `report.json` | Every result: ingest, verify, lint, page fit, ATS check. |
| `ats_view.txt` | The PDF's text as a parser extracts it. |

Exit codes: `0` ok, `1` a check failed, `2` usage or input error.

## Commands

| Command | What it does |
|---|---|
| `cvforge run <file> [--theme] [--pages N]` | The everyday command: all steps for one source. |
| `cvforge batch <dir> [--theme] [--pages N]` | `run` for every `.html` and `.tex` under a folder; keeps going after a failure, exits 1 if any failed. |
| `cvforge watch [<dir>...]` | `run` for files as they appear or change. Ctrl+C stops. |
| `cvforge tui [<dir>]` | Terminal UI: pick a resume, theme and page limit; see pages and checks. |
| `cvforge ingest <file> [-o path] [--extractor rules\|anthropic]` | Source to `resume.yaml`, then verify. |
| `cvforge verify <source> <yaml>` | The faithfulness check on its own. |
| `cvforge lint <yaml>` | Style warnings. Never changes anything, always exits 0. |
| `cvforge render <yaml> [--theme] [--pages N] [--formats pdf,docx,txt,md] [--out dir] [--force]` | YAML to output files, then the ATS check on the PDF. |
| `cvforge check <pdf> [--yaml resume.yaml] [--jd jd.txt]` | The ATS check on its own, with optional JD keyword coverage. |
| `cvforge themes [--preview] [--out dir]` | List themes; `--preview` writes `out/themes/<theme>-1.png`. |
| `cvforge export <yaml> --format jsonresume [-o file]` | Export to JSON Resume. |
| `cvforge schema` | Print the JSON Schema of `resume.yaml`. |
| `cvforge init [dir]` | Create `cvforge.toml` and an example `resume.yaml`. |

`batch`, `watch` and `tui` search subfolders but skip `out/`, `node_modules` and hidden folders.
`watch` with no folders uses `watch_dirs` from the config, and leaves alone files that were
already there when it started (use `batch` for those).

## Inputs

| Input | How much structure is recovered |
|---|---|
| `.html` (career-ops), `.tex` (ai-job-search) | Everything, via the class and macro maps in config. |
| `.json` (JSON Resume) | Everything; sections with no cvforge field become extra sections. |
| `.md` | Headings, bullets, skills lines, and entries written as below. |
| `.txt`, `.pdf` | Name, headline, contact line, headings, bullets and skills lines. Jobs and degrees are kept as plain lines and reported. PDF is a last resort and prints a warning. |

Markdown entries use the shape cvforge's own `.md` output has:

```
**Example Corp** | Pune, India
*Senior Data Engineer* | Jun 2023 – Present
- A bullet.
```

Anything the rules cannot place is kept word for word in an extra section and listed in the
output. Nothing is dropped silently; the only drops are the sections named in `drop_sections`
(default: `References`), and each one is reported on every run.

### Extractors

- **`rules`** (default): deterministic, no network.
- **Claude Code skill** (`.claude/skills/format-resume`): ask Claude Code to "format this
  resume". It runs the rules extractor, corrects the mapping by hand only if verification fails,
  then lints and renders.
- **`anthropic`** (optional): `uv sync --extra llm`, set `ANTHROPIC_API_KEY`, then
  `cvforge ingest cv.html --extractor anthropic`. The model is `llm_model` in the config. Its
  output goes through the same verification as the rules extractor.

## resume.yaml

`cvforge schema` prints the exact shape; `examples/resume.yaml` is a worked example. Points
worth knowing when editing by hand:

- **Dates** are `YYYY-MM` or `YYYY`; an ongoing role ends in `present`. They are displayed as
  `Jun 2023 – Present` (see `date_format`).
- **`**bold**`** is the only inline markup.
- **Several roles at one company** are separate `experience` entries; consecutive entries with
  the same company share one company line.
- **Links** show `text` when it is set and the URL without `https://` otherwise; either way the
  link target is the full `url`.
- **`extra_sections`** hold anything that fits no standard section. `after: skills` places one
  right after that section; without `after` it goes at the end. When every item is a short
  phrase the section renders on one line (`CI/CD | Snowflake | ...`) instead of as bullets.
- **Headings** render as standard words (Summary, Skills, Experience, ...). The source's own
  wording is kept under `meta.headings` and is used when `keep_heading_text = true`.

After a hand edit, `render` still works but warns that the YAML changed since it was verified.
If verification never passed, `render` refuses unless you pass `--force`. A YAML with no
`meta.source_file` (written by hand) has nothing to verify against and renders freely.

## The three checks

**Faithfulness** (`verify`, runs after every ingest):

| Check | Rule |
|---|---|
| Coverage | Every block of the source is in the YAML, whole or as the sum of its fields. |
| No additions | Every bullet, sentence, field, date, link and recorded heading is in the source. |
| Numbers | No numeric token (`40%`, `₹12L`, `5,000+`) that the source does not have. |
| Keywords | No technology named in the source is missing. Tech-shaped tokens are found automatically; `keywords.txt` lists ordinary-looking ones such as `dbt`. |
| Order | Bullets keep their source order. |

**ATS check** (`check`, runs after every render) extracts the PDF text with pdfplumber, pypdf
and, when installed, `pdftotext -layout`:

| Check | Rule |
|---|---|
| Name | In the first two lines. |
| Contact | Email, phone and link text extract intact, and every link is clickable through to its full URL. |
| Content and order | Every heading, line and bullet is present, in reading order. |
| Column-guessing parsers | A warning when `pdftotext -layout` reads right-aligned dates out of order. |
| Glyphs | No ligature glyphs, replacement characters, private-use characters, or words broken at a hyphen. |
| Headings | A warning for any non-standard heading (extra sections, or `keep_heading_text`). |
| PDF hygiene | Text on every page, fonts embedded, page size and count as configured, file size within `max_file_mb`. |
| JD keywords | With `--jd` only: which job-description keywords appear. Informational. |

There is no "ATS score". Each check passes, warns or fails, and names the exact strings.

**Lint** (`lint`) warns about long bullets and summaries, weak openers ("Responsible for"),
first-person pronouns, present tense in past roles, a keyword repeated in more than three
bullets, more than 35 skill items, near-duplicate bullets, and missing, mixed or overlapping
dates. It is advice about your wording and never changes it.

## Themes and page fitting

- **`classic`** (default): Source Serif 4, black, uppercase headings with a thin rule.
- **`modern`**: Inter, name on a full-width colour band, accent headings and bullets.
- **`compact`**: the classic look at the dense end of every range.

All themes are single column and share `themes/base.typ`; a theme is a folder with a
`theme.toml` of tokens (font, colours, sizes, spacing, margins) and a three-line `template.typ`.
`--theme` affects the PDF only; the DOCX is always Calibri with Word's built-in styles.

`--pages N` (or `pages` in the config) is the page limit. When a resume is over it, the layout
is tightened only as far as needed, in this order: section and entry spacing, line height, body
size (to 9.5pt at the least), margins (to 12mm at the least). If it still does not fit, nothing
is dropped: the command reports roughly how many lines over it is, lists the longest sections
and bullets, and exits 1.

## Configuration

`cvforge init` writes a `cvforge.toml` with every key and its default. cvforge reads it from the
folder you run in; with no file, the defaults apply.

| Key | Default | Meaning |
|---|---|---|
| `theme` | `"classic"` | Default theme. |
| `pages` | `2` | Page limit. |
| `paper` | `"a4"` | Or `"us-letter"`. |
| `formats` | all four | Which of `pdf`, `docx`, `txt`, `md` to write. |
| `date_format` | `"%b %Y"` | How `YYYY-MM` dates are shown. |
| `section_order` | Summary, Skills, Experience, Projects, Education, ... | Order of sections. Any you leave out still render, after the ones you list. |
| `keep_heading_text` | `false` | Render the source's heading wording. |
| `company_suffix` | `false` | `Jane_Doe_Resume_Acme.pdf` from `meta.target_company`. |
| `max_file_mb` | `2.0` | PDF size limit in the ATS check. |
| `drop_sections` | `["references"]` | Source headings to leave out (always reported). |
| `keywords_path` | `"keywords.txt"` | Extra keywords for verify; the bundled list if absent. |
| `llm_model` | `"claude-opus-5-5"` | Model for the `anthropic` extractor. |
| `watch_dirs` | `[]` | Folders for `watch` when none are given. |
| `[heading_synonyms]` | built in | Source heading to standard section. |
| `[html_classes]` | career-ops classes | HTML class to role (`org`, `title`, `dates`, ...). |
| `[latex_macros]` | moderncv macros | LaTeX macro to the role of each argument. |

The three tables add to the built-in defaults, so supporting a new HTML or LaTeX template is a
config change, for example `resumeSubheading = ["org", "location", "title", "dates"]`.

## Known limits

- Right-aligned dates on short entries (typically Education) are read out of order by
  column-guessing extractors such as `pdftotext -layout`. The text is all there; it is reported
  as a warning.
- Two sources with the same file name in different folders write to the same `out/<stem>/`.
- The DOCX is tested for structure, links and content order, but only the PDF goes through the
  ATS check.
- Lint's tense and keyword rules are heuristics and will occasionally misfire.
- The bundled fonts cover Latin scripts (including accents and symbols such as ₹ and €).
  Text in other scripts, such as Devanagari, Arabic or CJK, fails the ATS check by name
  rather than rendering wrongly in silence.
- A mistake in `cvforge.toml`, an unreadable source, or an output file that is read-only or
  open in another program stops the command with exit code 2 and a one-line reason.

## Development

```
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Tests use synthetic fixtures in `tests/fixtures/` only. `samples/` and `out/` hold personal data
and are gitignored. Bundled fonts in `fonts/` are under the SIL Open Font License; each family's
folder holds its license.
