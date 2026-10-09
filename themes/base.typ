// Shared single-column resume layout. Every theme's template.typ calls resume() with the
// data cvforge passes in; the look comes from the tokens in that theme's theme.toml.
// All content arrives as data: nothing here is built from user text.

#let resume(data) = {
  let t = data.theme
  let accent = rgb(t.accent)
  let muted = rgb(t.muted)
  let lead = (t.line_height - 1) * 1em
  let item-gap = t.item_gap * 1pt
  let band = t.header == "band"

  set document(title: data.name + " Resume", author: data.name, date: none)
  set page(paper: data.paper, margin: t.margin * 1mm)
  // Edges give every line a 1em box, so line height is exactly 1em + leading.
  set text(
    font: t.font, size: t.body_size * 1pt, lang: "en",
    hyphenate: false, ligatures: false, top-edge: 0.8em, bottom-edge: -0.2em,
  )
  set par(justify: false, leading: lead, spacing: lead)
  set block(spacing: lead)
  set list(
    marker: text(fill: if t.accent_bullets { accent } else { black }, [•]),
    indent: 0pt, body-indent: 0.6em, spacing: item-gap,
  )
  // Never break a line inside "on-call" or "YAML/JSON": split, a parser reads two broken words.
  show regex("\w+([-/]\w+)+"): box

  show heading: it => block(above: t.section_gap * 1pt, below: 5pt, sticky: true, {
    // Kerning off: tracking plus kerned pairs makes some parsers read "E D U C AT I O N".
    set text(
      size: t.heading_size * 1pt, weight: "bold", fill: accent,
      tracking: t.heading_tracking * 1em, kerning: false,
    )
    upper(it.body)
    if t.heading_rule {
      v(3pt, weak: true)
      line(length: 100%, stroke: 0.5pt + rgb(t.rule))
    }
  })

  let seg(s) = {
    let body = if s.at("bold", default: false) { strong(s.text) } else { s.text }
    if s.at("url", default: none) != none { link(s.url, body) } else { body }
  }
  let rich(segs) = segs.map(seg).join()

  // One line: text on the left, dates or location pushed right with h(1fr).
  let row(l, above) = block(above: above, sticky: true, {
    let left = rich(l.left)
    if l.style == "primary" { strong(left) } else if l.style == "secondary" { emph(left) } else { left }
    if l.right != "" {
      h(1fr)
      text(fill: muted, number-width: "tabular", l.right)
    }
  })

  let entry(b, above) = {
    for (i, l) in b.lines.enumerate() { row(l, if i == 0 { above } else { lead }) }
    for p in b.paragraphs { block(above: item-gap, rich(p)) }
    if b.bullets.len() > 0 { block(above: item-gap, list(..b.bullets.map(rich))) }
  }

  // Header: name, headline and contact line, all in the page body (never a PDF header).
  let ink = if band { white } else { accent }
  let header = {
    block(text(size: t.name_size * 1pt, weight: "bold", fill: ink, data.name))
    if data.headline != none {
      block(above: 6pt, text(size: t.headline_size * 1pt, data.headline))
    }
    // Each item is a box so the line wraps between items, never inside a URL or phone number.
    let sep = text(fill: if band { white.transparentize(45%) } else { muted }, " | ")
    block(above: 7pt, data.contact.map(c => box({
      if c.url != none { link(c.url, c.text) } else { c.text }
    })).join(sep))
  }
  if band {
    // A band of the accent colour bleeding to the page edges; the text stays ordinary body text.
    let edge = t.margin * 1mm
    block(
      width: 100%, fill: accent, below: t.section_gap * 1pt + 15pt,
      outset: (x: edge, top: edge, bottom: 13pt),
      text(fill: white, header),
    )
  } else {
    header
  }

  for s in data.sections {
    heading(s.heading)
    for (i, b) in s.blocks.enumerate() {
      let first = i == 0
      if b.kind == "entry" {
        entry(b, if first { 0pt } else if b.continued { item-gap + 1pt } else { t.entry_gap * 1pt })
      } else {
        let above = if first { 0pt } else { item-gap }
        if b.kind == "paragraph" { block(above: above, rich(b.segments)) }
        if b.kind == "labeled" { block(above: above, [#strong(b.label + ":") #rich(b.segments)]) }
        if b.kind == "bullets" { block(above: above, list(..b.items.map(rich))) }
        if b.kind == "inline" {
          block(above: above, b.items.map(rich).join(text(fill: muted, " | ")))
        }
      }
    }
  }
}
