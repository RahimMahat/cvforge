---
name: format-resume
description: Format, typeset, beautify or clean up a resume or CV file (.html from career-ops, .tex from ai-job-search) into an ATS-safe PDF with cvforge, without changing its content. Use when the user asks to format, typeset, beautify, prettify or clean up a resume or CV, or to make one ATS friendly.
---

# Format a resume with cvforge

cvforge typesets a resume without rewriting it. Your job here is to map the source onto
`resume.yaml` when the deterministic rules cannot, and nothing more. **You never change
content**: no rewording, no fixed grammar, no merged, split, added, dropped or reordered
bullets, no new numbers, skills, titles or dates.

Run commands as `uv run cvforge ...` inside the cvforge repo, or `cvforge ...` if it is
installed as a tool. `<stem>` below is the source file's name without its extension.

## Steps

1. **Ingest with the rules extractor.**

   ```
   cvforge ingest <path> --extractor rules
   ```

   This writes `out/<stem>/resume.yaml` and runs the faithfulness check. If every row of
   the Faithfulness table is PASS (exit code 0), go to step 4.

2. **Otherwise, correct the mapping by hand.**
   - Run `cvforge schema` to see the exact shape `resume.yaml` must have.
   - Read the source file and the partial `out/<stem>/resume.yaml`.
   - Write a corrected `out/<stem>/resume.yaml`, following these rules exactly:
     - Map content into the schema only.
     - Copy all text exactly.
     - Do not paraphrase, fix grammar, shorten, merge, split, add, drop, or reorder
       bullets within an entry.
     - You may normalize date formats (`YYYY-MM` or `YYYY`; an ongoing role ends in
       `present`).
     - Put anything you are unsure about into `extra_sections`.
   - The only inline markup is `**bold**`, kept exactly where the source has it.
   - Do not restore sections the tool reported as dropped: those are excluded on purpose
     by `drop_sections` in `cvforge.toml`.

3. **Verify.**

   ```
   cvforge verify <path> out/<stem>/resume.yaml
   ```

   - The table names every offending string. Fix *mapping* errors only: text in the wrong
     field, a missed block, a wrong date. Never edit the wording to make a check pass.
   - Stop after 3 attempts. If it still fails, report exactly which strings fail which
     check and do not render.

4. **Lint and render with the config defaults.**

   ```
   cvforge lint out/<stem>/resume.yaml
   cvforge render out/<stem>/resume.yaml
   ```

   - Show the user the lint warnings and the ATS check table as they are.
   - Do not act on lint warnings unless the user asks. They are advice about the user's
     own wording, which is theirs to change.
   - Tell the user where the PDF is (`out/<stem>/`) and mention anything the ingest step
     reported as dropped or kept verbatim in an extra section.

## If something fails

- `render` refuses with "failed against its source": verification has not passed. Go back
  to step 3; do not use `--force` unless the user explicitly asks for it.
- A FAIL in the ATS check after rendering is a layout problem, not a content problem.
  Report it with the named strings; do not edit the YAML to work around it.
- An unsupported file type exits with code 2. Only `.html` and `.tex` are supported.
