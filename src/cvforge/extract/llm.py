"""Optional extractor: Claude maps the SourceDoc onto the schema (`pip install cvforge[llm]`).

The model only does the mapping. Its output is validated against the schema and then goes
through the same verify step as the rules extractor, so a paraphrase cannot slip through.
"""

from typing import Any

from cvforge.config import Config
from cvforge.extract.rules import Extraction
from cvforge.ingest.sourcedoc import SourceDoc
from cvforge.models import Meta, Resume

# The mapping rules, verbatim from the spec (section 6.5).
INSTRUCTIONS = """\
You map resume content into a fixed schema. Follow these rules exactly:
- Map content into the schema only.
- Copy all text exactly.
- Do not paraphrase, fix grammar, shorten, merge, split, add, drop, or reorder bullets within \
an entry.
- You may normalize date formats.
- Put anything you are unsure about into `extra_sections`.

Schema notes:
- Dates are YYYY-MM or YYYY; an ongoing role ends in the word present.
- The only inline markup is **bold**; keep it exactly where the source has it.
- A link whose visible text is shorter than its URL keeps that text in `text` and the full \
URL in `url`.
- Leave `meta` empty; it is filled in afterwards.
- An extra section's `after` names the standard section it followed in the source."""


def source_prompt(doc: SourceDoc) -> str:
    """The pre-cleaned source as one block per line, with any role the template gave it."""
    lines = []
    for block in doc.blocks:
        tag = f"{block.kind}/{block.role}" if block.role else block.kind
        link = f"  <{block.url}>" if block.url else ""
        lines.append(f"[{tag}] {block.text}{link}")
    links = [f"- {link['text']} -> {link['url']}" for link in doc.links]
    return "\n".join(["SOURCE BLOCKS, in order:", *lines, "", "LINKS:", *links])


def extract_llm(doc: SourceDoc, config: Config, meta: Meta, client: Any = None) -> Extraction:
    """Ask Claude for a Resume. `client` is injectable for tests; by default it reads the
    key from ANTHROPIC_API_KEY (or another credential the SDK resolves)."""
    if client is None:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("the anthropic extractor needs: uv sync --extra llm") from exc
        client = anthropic.Anthropic()
    response = client.messages.parse(
        model=config.llm_model,
        max_tokens=16000,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": source_prompt(doc)}],
        output_format=Resume,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise RuntimeError(f"the model returned no usable resume (stop: {response.stop_reason})")
    resume = response.parsed_output.model_copy(update={"meta": meta})
    return Extraction(resume, unplaced=[])
