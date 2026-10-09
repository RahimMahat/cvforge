# Build spec: `cvforge` — a deterministic, ATS-safe resume formatter

Read this entire file before doing anything. It is the spec for a tool you will build with me, milestone by milestone.

---

## 0. How you must work

- **Before writing any code:** read this file, then inspect every file in `samples/`.
  - `samples/career-ops/` holds HTML resumes.
  - `samples/ai-job-search/` holds LaTeX resumes.
  - Then give me the "first response" described in Section 18 and wait for my reply.
- **Work in milestones (Section 16).** At the end of each one:
  1. Run `pytest -q`.
  2. Run the milestone's acceptance command and show me the output.
  3. Stop and wait for my approval.
- **Do not build anything not in this spec.** If you think something is missing, propose it in one line. Don't build it.
- **Verify current APIs** of third-party libraries (especially the `typst` Python package and `python-docx`) by reading their docs or installed source. Don't rely on memory.
- **Never commit `samples/` or `out/`.** They contain my personal data. Add both to `.gitignore` in the first commit.
- **Keep code clean:** small, typed functions; `ruff` for lint and format; one concern per module; small commits with clear messages.

---

## 1. Problem

I use two AI job-search tools:

| Tool | Output format | How it makes the PDF |
|---|---|---|
| **career-ops** | HTML | Rendered to PDF by a headless browser |
| **ai-job-search** | LaTeX (`.tex`) | Compiled to PDF |

Their **content** is good: tailored and keyword-rich. Their **formatting** is bad.

I want one tool that:
- takes either tool's output (or Markdown / JSON Resume / plain text);
- returns a beautifully typeset, ATS-friendly resume in PDF, DOCX, TXT and Markdown;
- leaves the content unchanged.

---

## 2. Non-negotiable principles

1. **Content is sacred.**
   - The tool restructures and typesets. It never rewrites, adds, removes, merges, splits or "improves" content.
   - No new metrics, skills, titles, dates or claims.
   - Every word in the output must trace back to the input.
2. **Content and layout are separate.**
   - Content lives in `resume.yaml`, the single source of truth. I can edit it by hand.
   - Layout lives in templates.
   - Rendering is deterministic: the same YAML and theme give the same text output every time.
   - No LLM anywhere in the rendering path.
3. **An LLM is used only at ingestion**, to map messy markup onto the schema. It is always followed by an automatic faithfulness check (Section 7).
4. **ATS-first layout rules:**
   - single column, real selectable text;
   - standard section headings;
   - no tables, grids, text boxes, multi-column layouts, images or icons for layout;
   - contact info in the body, never in a header or footer;
   - hyphenation off, ligatures off, left-aligned (not justified) text.
5. **Beauty comes from typography, spacing and hierarchy**, not graphics.
6. **Fail loudly.** If a check fails, exit non-zero and print a report naming the exact offending strings.

---

## 3. Context and defaults

- **Me:** a Python data engineer, comfortable with CLI, YAML and git. Applying mainly in India, later possibly the Netherlands and Singapore.
- **Paper:** A4 by default; Letter via config.
- **Personal details:** no photo, date of birth, marital status or full street address. Location is city plus country only.
- **Length:** at most 2 pages by default; configurable with `--pages N`.

---

## 4. Architecture

```
input (.html | .tex | .md | .json | .txt | .pdf-fallback)
   │  1. pre-clean (deterministic) → SourceDoc: ordered blocks + raw_text
   ▼
   │  2. extract → schema
   │     (rules parser | Claude Code skill | Anthropic API)
   ▼
resume.yaml   ← single source of truth, hand-editable
   │  3. verify faithfulness against source (blocks render on failure)
   │  4. lint (warnings only)
   ▼
   │  5. render: Typst → PDF | python-docx → DOCX | TXT | MD
   ▼
   │  6. ATS check on the rendered PDF (multi-extractor)
   ▼
out/<source-stem>/ : PDF, DOCX, TXT, MD, resume.yaml, report.json, ats_view.txt
```

---

## 5. Canonical schema

- Use Pydantic v2 models.
- Stay JSON Resume-compatible where possible, and support `cvforge export --format jsonresume`.
- `cvforge schema` prints the JSON Schema.

```yaml
meta:
  source_file: samples/career-ops/acme-senior-de.html
  source_tool: career-ops          # career-ops | ai-job-search | manual | other
  target_role: Senior Data Engineer   # optional, only if present in the source
  target_company: Acme                # optional, only if present in the source
basics:
  name: Jane Doe
  headline: Senior Data Engineer      # optional
  email: jane@example.com
  phone: "+91 90000 00000"
  location: Pune, India
  links:
    - label: LinkedIn
      url: https://linkedin.com/in/janedoe
    - label: GitHub
      url: https://github.com/janedoe
summary: >-
  One short paragraph, copied verbatim from the source.
skills:
  - category: Languages
    items: [Python, SQL]
  - category: AWS
    items: [Glue, S3, Lambda, Redshift, Athena]
experience:
  - company: Example Corp
    title: Senior Data Engineer
    location: Pune, India
    start: 2023-06
    end: present
    bullets:
      - Built **AWS Glue** pipelines processing ... (verbatim)
projects:
  - name: ...
    url: ...            # optional
    tech: [..]          # optional, only if present in the source
    bullets: [...]
education:
  - institution: ...
    degree: ...
    field: ...
    start: 2017
    end: 2021
    details: []         # optional lines, e.g. GPA, only if present
certifications: []      # render only if non-empty
awards: []
publications: []
languages: []
extra_sections:          # anything that doesn't fit; preserved verbatim, never dropped
  - title: Volunteering
    items: [...]
```

**Rules:**
- **Dates** are `YYYY-MM` or `YYYY`. `end: present` is allowed.
- **Inline markup:** the only markup allowed in text fields is `**bold**`.
- **Unknown sections** go to `extra_sections`. Nothing is ever silently dropped.
- **Empty sections** are not rendered.
- **Several roles at one company** are separate `experience` entries. The renderer groups consecutive entries with the same company: company shown once, roles listed underneath.
- **YAML I/O** uses `ruamel.yaml` to preserve comments and key order, so my hand edits survive round-trips.

---

## 6. Ingestion

### 6.1 Pre-clean (deterministic)

- Detect the input type by file extension, then by content sniffing.
- Produce a `SourceDoc`:
  - `blocks`: an ordered list of `{kind: heading|paragraph|bullet|line, level, text}`;
  - `raw_text`: normalized plain text, used by the faithfulness check;
  - `links`: a list of `{text, url}`.

### 6.2 HTML (career-ops)

- Use BeautifulSoup with the `lxml` parser.
- Drop `<script>`, `<style>`, `<head>` (keep `<title>`) and hidden elements.
- Map elements:
  - `h1`–`h4` → headings;
  - `li` → bullets;
  - `p` / `div` text → paragraphs or lines;
  - `<strong>` / `<b>` → `**bold**`;
  - `<a href>` → link records.
- Inspect `samples/career-ops/` first. If its template uses stable class names for sections or entries, use them. Otherwise fall back to tag structure.

### 6.3 LaTeX (ai-job-search)

- Parse the `.tex` source. Never compile it.
- Strip the preamble before `\begin{document}`.
- Strip comments (`%` to end of line), respecting escaped `\%`.
- Map structure:
  - `\section` / `\subsection` → headings.
  - Resume macros (e.g. `\resumeSubheading{}{}{}{}`, `\resumeItem{}`, `\cventry{}`) → entries and bullets. **Discover the real macros from `samples/ai-job-search/`.**
- Keep a **macro map** in `cvforge.toml`: macro name → block kind and argument roles (company, title, dates, location…). New templates should be supportable by editing config, not code.
- Convert inline markup:
  - escapes: `\&`, `\%`, `\_`, `\#`, `\$` → the literal characters;
  - dashes: `--` → en dash, `---` → em dash;
  - `~` → space;
  - `\textbf{}` → `**bold**`;
  - `\href{url}{text}` and `\url{}` → link records.
- Use `pylatexenc` for the remaining text conversion.

### 6.4 Other inputs

- Markdown, JSON Resume and plain text: straightforward mappings.
- PDF: fallback only, via `pdfplumber`. Warn that structure may be lost.

### 6.5 Extractors (`--extractor`)

1. **`rules`** (default) — deterministic mapping from `SourceDoc`.
   - Uses heading synonyms from config (e.g. "Work Experience" / "Professional Experience" → `experience`; "Technical Skills" → `skills`).
   - Recognizes date ranges with a regex.
   - Any block it can't place goes to `extra_sections` and is listed in the report.
2. **`claude-code`** — the mapping is done by the Claude Code skill (Section 12). No API key needed.
3. **`anthropic`** (optional extra `[llm]`) — calls the Anthropic Messages API.
   - Uses tool use / structured output against the JSON Schema.
   - Model comes from config; the key comes from env `ANTHROPIC_API_KEY`.

**Instructions for any LLM extraction** (put these in the prompt verbatim):
- Map content into the schema only.
- Copy all text exactly.
- Do not paraphrase, fix grammar, shorten, merge, split, add, drop, or reorder bullets within an entry.
- You may normalize date formats.
- Put anything you are unsure about into `extra_sections`.

---

## 7. Faithfulness guard: `cvforge verify <source> <yaml>`

**When it runs:** automatically after every `ingest`.

**Sidecar file:** it writes `resume.yaml.verified` containing the YAML hash and the result.

**What `render` does with that file:**
- If verification never passed, `render` refuses to run unless `--force` is given. With `--force`, the report records that verification failed.
- If the YAML changed after a passing verification (my hand edits), `render` prints a warning but proceeds. My edits are allowed.

**Normalization before comparing:** lowercase; collapse whitespace; unify dashes, quotes and bullet glyphs; strip `**`.

**Checks:**

| Check | Rule |
|---|---|
| Coverage | Every source bullet or sentence has a YAML match with `rapidfuzz` ratio ≥ 95. List each one that doesn't. |
| No additions | Every YAML bullet or sentence has a source match ≥ 95. List each one that doesn't. |
| Numbers | Numeric tokens in the YAML (including `%`, `₹`, `$`, `x`, `k`, `M`, `+`) must be a subset of those in the source. |
| Keywords | Every keyword in the source must appear in the YAML. Keywords are: skills-section items; tech-looking tokens (CamelCase, ALLCAPS, tokens with digits, `.`, `+` or `#`); and terms from a dictionary file `keywords.txt`, which I can extend. |
| Order | Bullets within each entry keep their source order. |

**Output:** a Rich table with PASS/FAIL per check, plus the exact offending strings. The same data goes into `report.json`.

---

## 8. Rendering

### 8.1 Typst (PDF)

**Compiling:**
- Use the `typst` PyPI package to compile from Python, passing font paths and inputs. Fall back to the `typst` CLI if it's installed.
- Fonts: bundle OFL-licensed fonts in `fonts/` and pass them as font paths. Never depend on system fonts.

**Escaping:** never build Typst source by concatenating user text.
- Write the resume as JSON to a temp dir and have the template load it with `json(...)`. This avoids escaping bugs with `# $ * _ @ < > \ \``.
- `**bold**` is pre-split in Python into segments like `[{"text": ..., "bold": true}]`, and the template renders the segments.
- Never `eval` user text.

**Global settings in every template:**
- `set document(title: ..., author: ...)`
- `set text(lang: "en", hyphenate: false, ligatures: false)`
- `set par(justify: false)`

**Entry layout:**
- Line 1: **company** on the left, location on the right.
- Line 2: title on the left, dates on the right.
- Right alignment uses `h(1fr)` on the same line, not tables or grids.
- Bullets use `•` with a hanging indent.
- Each section heading is kept together with its first entry (no orphaned heading at the bottom of a page).

**Contact line:**
- Placed in the body, directly under the name.
- Items separated by ` | `.
- Links are shown as visible text (e.g. `linkedin.com/in/janedoe`, without `https://`) and are hyperlinked.

**Headings:**
- Render standard words only: Summary, Skills, Experience, Projects, Education, Certifications, Awards, Publications, Languages.
- Map synonyms to these, unless config sets `keep_heading_text = true`.

**Skills:** one line per category, e.g. **Languages:** Python, SQL.

**Section order:** configurable. The default is Summary, Skills, Experience, Projects, Education, then the rest.

### 8.2 Themes

All themes are single column. Each theme is a folder containing:
- `template.typ`;
- `theme.toml` with the font family, sizes, accent color, margins, spacing and heading style.

| Theme | Look |
|---|---|
| `classic` | Clean, "Jake's Resume"-like. Uppercase section headings with a thin full-width rule; black text; serif or neutral sans. |
| `modern` | Sans-serif (e.g. Inter or Source Sans 3). Large name; one muted accent color (e.g. `#1F3A5F`) used only for the name and section headings; generous whitespace. |
| `compact` | Denser spacing for one-page fitting. Body text still at least 10pt. |

**Design tokens** (theme defaults must stay inside these ranges):

| Element | Value |
|---|---|
| Name | 22–26pt |
| Headline | 11–12pt |
| Section headings | 10.5–11.5pt, uppercase, letter-spacing 0.06–0.1em |
| Body | 10–10.5pt (absolute minimum 9.5pt, and only during fitting) |
| Line height | ~1.2–1.3 |
| Section gap | 10–12pt |
| Entry gap | 6–8pt |
| Margins | 14–18mm (minimum 12mm, and only during fitting) |
| Accent color | At most one |
| Dates and locations | Lighter gray, contrast ≥ 4.5:1 |
| Figures | Tabular figures for dates, if the font supports them |

`cvforge themes --preview` renders a synthetic fixture with every theme to PNG, so I can compare them side by side.

### 8.3 Page fitting (`--pages N`)

1. Compile and count pages with `pypdf`.
2. If over the limit, step down within theme bounds, in this order:
   1. section and entry spacing;
   2. line height;
   3. body size;
   4. margins.
3. Stop after at most 8 iterations.
4. If it still doesn't fit:
   - **Never drop content.**
   - Report how many lines over it is, plus the longest sections and bullets.
5. Also warn if the last page is less than 15% filled.

### 8.4 DOCX (python-docx)

- Same content and order as the PDF.
- Single column.
- Use built-in styles (`Title`, `Heading 1`, `Heading 2`, `List Bullet`) so parsers detect structure.
- Calibri or Arial, 10–11pt.
- Right-align dates with a right tab stop at the margin, not tables.
- Contact info in the body, not the header. No text boxes.

### 8.5 TXT and Markdown

Plain versions for pasting into job-portal text fields.

### 8.6 Output naming

Write everything to `out/<source-stem>/`:
- `<First>_<Last>_Resume.pdf` — an optional `_<Company>` suffix can be enabled in config;
- the same name as `.docx`, `.txt` and `.md`;
- `resume.yaml`;
- `report.json`;
- `ats_view.txt`.

---

## 9. ATS check: `cvforge check <pdf> [--yaml resume.yaml] [--jd jd.txt]`

**Text extraction:**
- Use at least two independent extractors: `pdfplumber`/`pdfminer.six` and `pypdf`. Also use `pdftotext -layout` if it's installed.
- Save the primary extraction to `ats_view.txt`: what a parser would see.

**Checks:**

| Check | Rule |
|---|---|
| Name | The name is in the first 2 lines of extracted text. |
| Contact | Email, phone (Indian and international formats) and every link URL are extractable as plain text. |
| Content and order | Every heading and bullet from the YAML appears in the extracted text, in the same order (fuzzy ≥ 95 after normalization). |
| Glyphs | No ligature glyphs (ﬁ ﬂ ﬀ ﬃ ﬄ), no replacement characters (�), no private-use-area characters, no words broken by hyphens at line ends. |
| Headings | Only standard section headings. |
| PDF hygiene | Text layer on every page; fonts embedded; page size and count as configured; file size ≤ `max_file_mb` (default 2). |
| JD (only with `--jd`) | Keyword coverage table: found and missing. Informational only, never a failure. |

**Rules:**
- Report pass / warn / fail per check.
- **No invented "ATS score %".**
- Exit code 1 if any check fails.

---

## 10. Lint: `cvforge lint <yaml>`

Warnings only. Never auto-fix.

- A bullet longer than ~220 characters (more than ~2 rendered lines).
- The same keyword appears more than 3 times across bullets (keyword-stuffing smell).
- More than 35 skill items in total.
- Bullets starting with "Responsible for", "Worked on", "Helped", "Assisted".
- First-person pronouns (I, my, me).
- Present-tense verbs in past roles.
- Missing dates, mixed date formats, overlapping dates.
- Duplicate or near-duplicate bullets across entries.
- A summary longer than 4 rendered lines.

Output a table with the location of each warning (section / entry / bullet index).

---

## 11. CLI

Use Typer for the commands and Rich for output.

| Command | What it does |
|---|---|
| `cvforge init` | Creates `cvforge.toml` and an example `resume.yaml`. |
| `cvforge schema` | Prints the JSON Schema. |
| `cvforge ingest <file> [--extractor rules\|anthropic] [-o path]` | Writes the YAML and runs verify. |
| `cvforge verify <source> <yaml>` | Runs the faithfulness guard. |
| `cvforge lint <yaml>` | Prints lint warnings. |
| `cvforge render <yaml> [--theme] [--pages] [--formats pdf,docx,txt,md] [--out]` | Renders the outputs, then runs `check` automatically on the PDF. |
| `cvforge check <pdf> [--yaml] [--jd]` | Runs the ATS check. |
| `cvforge run <file> [--theme] [--pages]` | The everyday command: ingest → verify → lint → render → check. |
| `cvforge batch <dir>` | Processes every `.html` / `.tex` file in a folder. |
| `cvforge watch <dir>...` | Processes new or changed files as they appear. I'll point it at both tools' output folders. |
| `cvforge themes [--preview]` | Lists themes; `--preview` renders them for comparison. |
| `cvforge export <yaml> --format jsonresume` | Exports to JSON Resume. |

**Exit codes:** 0 = OK; 1 = checks failed; 2 = usage or input error.

**`cvforge.toml` holds:**
- default theme, page limit, paper size and formats;
- output naming;
- heading synonyms;
- the LaTeX macro map;
- the keyword dictionary path;
- the LLM model;
- the watch directories.

---

## 12. Claude Code skill

Create `.claude/skills/format-resume/SKILL.md`. It should trigger when I ask to format, typeset, beautify or clean up a resume or CV file. Its steps:

1. Run `cvforge ingest <path> --extractor rules`. If verification passes, go to step 4.
2. Otherwise:
   - run `cvforge schema`;
   - read the source file and the partial YAML;
   - write a corrected `resume.yaml`, following the verbatim mapping rules in Section 6.5.
3. Run `cvforge verify`.
   - Fix *mapping* errors only, never content.
   - Stop after 3 attempts and report exactly what still fails.
4. Run `cvforge lint` and `cvforge render` with config defaults.
   - Show me the lint warnings and the check report.
   - Do not act on lint warnings unless I ask.

---

## 13. Project layout

```
cvforge/
  pyproject.toml
  README.md
  cvforge.toml.example
  keywords.txt
  .gitignore                # samples/, out/, .venv/
  src/cvforge/
    cli.py
    config.py
    models.py
    yaml_io.py
    ingest/{__init__,sourcedoc,html,latex,markdown,jsonresume,text,pdf}.py
    extract/{rules,llm}.py
    verify.py
    lint.py
    render/{typst_renderer,docx_renderer,text_renderer,segments,fit}.py
    check/{extract_text,ats,report}.py
  themes/{classic,modern,compact}/{template.typ,theme.toml}
  fonts/                    # OFL fonts + their licenses
  .claude/skills/format-resume/SKILL.md
  tests/
    fixtures/               # synthetic data only
  samples/                  # my real files — gitignored, never copied into tests
  out/                      # gitignored
```

---

## 14. Tech stack

- **Core:** Python 3.12, `uv`, Typer, Rich, Pydantic v2, `ruamel.yaml`, `typst` (PyPI), `pypdf`, `pdfplumber`, `python-docx`, `beautifulsoup4` + `lxml`, `pylatexenc`, `rapidfuzz`.
- **Dev:** `pytest`, `ruff`.
- **Optional extras:**
  - `[llm]` — `anthropic`
  - `[watch]` — `watchdog`
  - `[tui]` — `textual`
- The tool is installed with `uv tool install .` and exposes the `cvforge` command.

---

## 15. Testing

**Fixtures:** synthetic only, in `tests/fixtures/`:
- an HTML resume in the career-ops style;
- a LaTeX resume using common resume macros;
- a Markdown resume.

Never copy content from `samples/` into tests.

**Tests:**
- **Golden:** each fixture ingests to the expected YAML.
- **Faithfulness:** tampered YAML must fail verify. Cover these cases:
  - an added metric;
  - a dropped keyword;
  - a paraphrased bullet;
  - reordered bullets;
  - a dropped section.
- **Render:** for each theme, render a fixture and confirm `check` passes. Fixtures must include words like "efficient", "workflow", "Kubernetes" and "PySpark" in long lines, to prove hyphenation and ligatures are off.
- **Escaping:** content containing `# $ * _ @ < > & % { } \` and backticks renders correctly in both PDF and DOCX.
- **Fitting:** an oversized fixture either fits within bounds, or reports the overflow without dropping content.

`pytest -q` must pass at the end of every milestone.

---

## 16. Milestones

Stop after each one for my review.

| # | Scope | Acceptance |
|---|---|---|
| M1 | Skeleton, `models.py`, `schema`, `init`, example YAML, `.gitignore` | `uv run cvforge schema` prints valid JSON Schema; tests pass |
| M2 | Typst render, `classic` theme, bundled fonts, segment-based escaping | `cvforge render examples/resume.yaml` produces a PDF; escaping tests pass |
| M3 | `check` + `lint` + `report.json` + `ats_view.txt` | All checks pass on the `classic` render of the fixture |
| M4 | HTML + LaTeX pre-clean, `rules` extractor, `verify`, `run` | `cvforge run` on every file in `samples/` either passes verify or names exactly what it couldn't map |
| M5 | Claude Code skill, optional `anthropic` extractor | Skill formats a sample end to end inside Claude Code |
| M6 | `modern` + `compact` themes, `themes --preview`, page fitting | Previews render; fitting test passes |
| M7 | DOCX, TXT, MD outputs; `batch` + `watch` | All formats produced; `watch` picks up a newly dropped file |
| M8 | *(only if I ask)* Textual TUI: pick file, theme and page target; live page count and check status | — |

---

## 17. Out of scope

- Job search, scraping, JD matching and tailoring — my other tools do this.
- Rewriting, polishing or "improving" content in any form.
- Cover letters.
- Web UI, accounts, hosting.
- Multi-column layouts, photos, icons, skill bars, charts.

---

## 18. Your first response

1. For each tool's samples, what you found: structure, sections, HTML classes, LaTeX macros, edge cases.
2. Your plan for M1–M4, plus any deviations from this spec and why.
3. Questions wherever this spec is ambiguous.

Do not write code until I reply.
