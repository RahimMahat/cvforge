"""Plain-text and Markdown versions of the render view, for pasting into job portals."""

from typing import Any

from cvforge.render.segments import Segment
from cvforge.render.view import display_url

_SEP = " | "


def _plain(segments: list[Segment]) -> str:
    return "".join(segment["text"] for segment in segments)


def _markdown(segments: list[Segment]) -> str:
    out = []
    for segment in segments:
        text = f"**{segment['text']}**" if segment.get("bold") else segment["text"]
        out.append(f"[{text}]({segment['url']})" if segment.get("url") else text)
    return "".join(out)


def _contact(item: dict[str, Any], markdown: bool) -> str:
    text, url = item["text"], item["url"] or ""
    if not url.startswith("http"):
        return text
    # Plain text cannot hide a target behind short text, so it shows the real URL.
    return f"[{text}]({url})" if markdown else display_url(url)


def _entry(block: dict[str, Any], markdown: bool) -> list[str]:
    lines = []
    for line in block["lines"]:
        left = _plain(line["left"])
        if markdown and left:
            mark = {"primary": "**", "secondary": "*"}.get(line["style"], "")
            url = next((s["url"] for s in line["left"] if s.get("url")), None)
            left = f"{mark}{f'[{left}]({url})' if url else left}{mark}"
        lines.append(_SEP.join(part for part in (left, line["right"]) if part))
    rich = _markdown if markdown else _plain
    lines += [rich(paragraph) for paragraph in block["paragraphs"]]
    if markdown:  # two trailing spaces keep each header line on its own line
        lines = [f"{line}  " for line in lines[:-1]] + lines[-1:]
    return lines + [f"- {rich(bullet)}" for bullet in block["bullets"]]


def _block(block: dict[str, Any], markdown: bool) -> list[str]:
    rich = _markdown if markdown else _plain
    match block["kind"]:
        case "paragraph":
            return [rich(block["segments"])]
        case "labeled":
            label = f"**{block['label']}:**" if markdown else f"{block['label']}:"
            return [f"{label} {rich(block['segments'])}"]
        case "bullets":
            return [f"- {rich(item)}" for item in block["items"]]
        case "inline":
            return [_SEP.join(rich(item) for item in block["items"])]
    return _entry(block, markdown)


def render_text(view: dict[str, Any], markdown: bool = False) -> str:
    """The whole resume as text. Markdown keeps bold and links; plain text drops both."""
    lines = [f"# {view['name']}" if markdown else view["name"]]
    if view["headline"]:
        lines += ["", view["headline"]] if markdown else [view["headline"]]
    contact = _SEP.join(_contact(item, markdown) for item in view["contact"])
    lines += ["", contact] if markdown else [contact]
    for section in view["sections"]:
        heading = f"## {section['heading']}" if markdown else section["heading"].upper()
        lines += ["", heading] + ([""] if markdown else [])
        for i, block in enumerate(section["blocks"]):
            # Markdown needs a blank line between blocks; plain text only between entries.
            new_entry = block["kind"] == "entry" and not block["continued"]
            labeled_run = block["kind"] == "labeled" and markdown
            if i and (new_entry or (markdown and not labeled_run)):
                lines.append("")
            body = _block(block, markdown)
            lines += [f"{line}  " for line in body] if labeled_run else body
    return "\n".join(line.rstrip() if not markdown else line for line in lines).rstrip() + "\n"
