#!/usr/bin/env python3
"""Build the claude-code-tips public site from README.md.

Parses README.md (the canonical source) into structured sections and renders a
single-file HTML site styled to feel like the Claude Code CLI: dark warm
background, all-mono type, terminal-framed cards, coral accent.

Output: dist/index.html (single file, inline CSS + JS).
Dependencies: markdown (Python-Markdown).
"""

from __future__ import annotations

import html
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import markdown
except ImportError:
    sys.stderr.write("error: missing dependency 'markdown' (pip install markdown)\n")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OUT_DIR = ROOT / "dist"
OUT_FILE = OUT_DIR / "index.html"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@dataclass
class Tip:
    num: int
    title: str
    slug: str
    advice_md: str = ""
    technical_md: str = ""
    cta_md: str = ""
    sources_md: str = ""


@dataclass
class ParsedDoc:
    title: str = ""
    intro_md: str = ""
    how_to_use_md: str = ""
    tldr_md: str = ""
    tips: list[Tip] = field(default_factory=list)
    anti_patterns_md: str = ""
    sources_md: str = ""


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def split_top_heading(text: str) -> tuple[str, str]:
    """Return (h1_title, rest_of_doc) splitting on the first '# ' line."""
    m = re.search(r"^# (.+)$", text, flags=re.MULTILINE)
    if not m:
        return "", text
    title = m.group(1).strip()
    rest = text[m.end():]
    return title, rest


def split_by_h_with_fence(text: str, level: int) -> list[tuple[str, str]]:
    """Split text into (heading_title, body) tuples on '## '/'### ' headings.

    Fence-aware: ignores headings that appear inside a triple-backtick fence.
    Returns the preamble (text before the first heading) as ('', preamble) if
    non-empty, otherwise the first element is the first heading.
    """
    prefix = "#" * level + " "
    in_fence = False
    chunks: list[tuple[str, list[str]]] = []
    preamble: list[str] = []
    current: tuple[str, list[str]] | None = None

    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            (current[1] if current is not None else preamble).append(line)
            continue
        if not in_fence and line.startswith(prefix):
            if current is not None:
                chunks.append(current)
            current = (line[len(prefix):].strip(), [])
            continue
        (current[1] if current is not None else preamble).append(line)

    if current is not None:
        chunks.append(current)

    result: list[tuple[str, str]] = []
    pre = "\n".join(preamble).strip()
    if pre:
        result.append(("", pre))
    for title, body_lines in chunks:
        result.append((title, "\n".join(body_lines).strip()))
    return result


SOURCES_MARK_RE = re.compile(r"(?ms)^\*\*Sources:\*\*\s*\n?(?P<list>.*)$")


def pull_sources(body: str) -> tuple[str, str]:
    """Split a trailing '**Sources:**' block off a subsection body.

    Returns (body_without_sources, sources_md). The sources_md is whatever
    follows the '**Sources:**' label (a markdown bullet list in the README).
    """
    if not body:
        return body, ""
    m = SOURCES_MARK_RE.search(body)
    if not m:
        return body, ""
    before = body[: m.start()].rstrip()
    sources = m.group("list").strip()
    return before, sources


def slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "section"


def short_slug(title: str, max_words: int = 3) -> str:
    """Build a short id-friendly slug from a tip title."""
    s = re.sub(r"[^\w\s-]", "", title.lower())
    words = [w for w in s.split() if w and w not in {"the", "a", "an", "to", "in", "of", "on"}]
    return "-".join(words[:max_words]) or "tip"


def parse_readme(text: str) -> ParsedDoc:
    text = strip_frontmatter(text)
    title, rest = split_top_heading(text)
    doc = ParsedDoc(title=title or "Claude Code Engineering Tips")

    # Pre-amble before first ## becomes intro_md.
    sections = split_by_h_with_fence(rest, level=2)

    # First entry may be ("", intro)
    if sections and sections[0][0] == "":
        # Strip the standalone '---' divider lines that separate sections.
        intro = sections[0][1]
        intro = re.sub(r"^\s*---\s*$", "", intro, flags=re.MULTILINE)
        # Drop README-only chrome (hero image, shield badges) so it doesn't
        # leak into the site's own terminal hero, which has its own header.
        intro = re.sub(
            r"^\s*\[?!\[[^\]]*\]\([^)]*\)(?:\]\([^)]*\))?\s*$",
            "",
            intro,
            flags=re.MULTILINE,
        )
        intro = re.sub(r"\n{3,}", "\n\n", intro).strip()
        doc.intro_md = intro
        sections = sections[1:]

    for h2_title, body in sections:
        body = re.sub(r"^\s*---\s*$", "", body, flags=re.MULTILINE).strip()
        m = re.match(r"^(\d+)\.\s+(.+)$", h2_title)
        if m:
            num = int(m.group(1))
            tip_title = m.group(2).strip()
            tip = Tip(
                num=num,
                title=tip_title,
                slug=f"tip-{num:02d}",
            )
            subs = split_by_h_with_fence(body, level=3)
            for sub_title, sub_body in subs:
                key = sub_title.lower()
                if "advice" in key:
                    tip.advice_md = sub_body
                elif "technical" in key:
                    tip.technical_md = sub_body
                elif "your turn" in key or "call to action" in key or key == "cta":
                    tip.cta_md = sub_body
            # Sources now live at the tail of the "Your Turn" subsection. Fall
            # back to the technical section for older layouts.
            tip.cta_md, sources = pull_sources(tip.cta_md)
            if not sources:
                tip.technical_md, sources = pull_sources(tip.technical_md)
            tip.sources_md = sources
            doc.tips.append(tip)
        elif "tl;dr" in h2_title.lower():
            doc.tldr_md = body
        elif "how to use" in h2_title.lower():
            doc.how_to_use_md = body
        elif "anti-pattern" in h2_title.lower():
            doc.anti_patterns_md = body
        elif "sources" in h2_title.lower():
            doc.sources_md = body
        # else: unknown section, ignored

    doc.tips.sort(key=lambda t: t.num)
    return doc


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def make_markdown() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=["fenced_code", "tables", "attr_list", "sane_lists", "nl2br"],
        output_format="html5",
    )


_MD = make_markdown()


def md_to_html(text: str) -> str:
    if not text:
        return ""
    _MD.reset()
    rendered = _MD.convert(text)
    return enhance_code_blocks(rendered)


CODE_BLOCK_RE = re.compile(
    r'<pre><code(?P<attrs>[^>]*)>(?P<body>.*?)</code></pre>',
    re.DOTALL,
)


def enhance_code_blocks(html_text: str) -> str:
    """Wrap each fenced code block in a styled terminal frame with a copy button."""

    def repl(m: re.Match[str]) -> str:
        attrs = m.group("attrs") or ""
        body = m.group("body")
        lang_match = re.search(r'class="language-([^"]+)"', attrs)
        lang = lang_match.group(1) if lang_match else ""
        label = lang or "sh"
        return (
            '<figure class="code-frame">'
            '<div class="code-bar">'
            f'<span class="code-label">▮ {html.escape(label)}</span>'
            '<button class="code-copy" type="button" aria-label="Copy code">copy</button>'
            '</div>'
            f'<pre class="code-body"><code{attrs}>{body}</code></pre>'
            '</figure>'
        )

    return CODE_BLOCK_RE.sub(repl, html_text)


def tldr_with_links(tldr_md: str, tips: list[Tip]) -> str:
    """Render TL;DR list items with each numbered entry linked to its tip card."""
    html_text = md_to_html(tldr_md)
    # Inject anchor wrappers around each <li>'s text content.
    by_num = {t.num: t for t in tips}

    def repl(m: re.Match[str]) -> str:
        index = int(m.group("idx"))
        inner = m.group("body")
        tip = by_num.get(index)
        if not tip:
            return m.group(0)
        return (
            f'<li value="{index}" data-tip="{tip.num:02d}">'
            f'<a class="tldr-link" href="#{tip.slug}">{inner}</a>'
            '</li>'
        )

    # Walk through <ol> children to assign indices.
    counter = {"i": 0}

    def li_repl(match: re.Match[str]) -> str:
        counter["i"] += 1
        idx = counter["i"]
        inner = match.group("body")
        tip = by_num.get(idx)
        if not tip:
            return match.group(0)
        return (
            f'<li value="{idx}" data-tip="{tip.num:02d}">'
            f'<a class="tldr-link" href="#{tip.slug}">{inner}</a>'
            '</li>'
        )

    return re.sub(r"<li>(?P<body>.*?)</li>", li_repl, html_text, flags=re.DOTALL)


def render_sidebar(doc: ParsedDoc) -> str:
    items = []
    for tip in doc.tips:
        items.append(
            f'<li data-tip="{tip.num:02d}">'
            f'<a href="#{tip.slug}">'
            f'<span class="toc-num">{tip.num:02d}</span>'
            f'<span class="toc-title">{html.escape(tip.title)}</span>'
            '</a>'
            '</li>'
        )
    tips_list = "\n          ".join(items)
    return f'''
      <div class="sidebar-header">
        <div class="logo">~/claude-code-tips</div>
        <div class="logo-sub">14 habits / less spend</div>
      </div>
      <div class="search-wrap">
        <span class="search-prompt">/</span>
        <input id="search" type="search" placeholder="filter tips" autocomplete="off" spellcheck="false">
        <span class="search-hint">press / to focus</span>
      </div>
      <nav class="toc" aria-label="Tips">
        <div class="toc-section-label">$ tldr</div>
        <ul class="toc-extras">
          <li><a href="#tldr"><span class="toc-num">▸</span><span class="toc-title">tl;dr</span></a></li>
        </ul>
        <div class="toc-section-label">$ tips</div>
        <ol class="toc-list">
          {tips_list}
        </ol>
        <div class="toc-section-label">$ also</div>
        <ul class="toc-extras">
          <li><a href="#anti-patterns"><span class="toc-num">!</span><span class="toc-title">anti-patterns</span></a></li>
          <li><a href="#sources"><span class="toc-num">¶</span><span class="toc-title">sources</span></a></li>
          <li><a href="https://github.com/JuanjoFuchs/claude-code-tips" target="_blank" rel="noopener"><span class="toc-num">↗</span><span class="toc-title">github</span></a></li>
        </ul>
      </nav>
      <div class="sidebar-footer">
        <span class="status-dot"></span>
        <span class="status-text">all systems nominal</span>
      </div>
    '''


def render_tip(tip: Tip) -> str:
    sections = []
    if tip.advice_md:
        sections.append(
            f'<section class="subsection">'
            f'<h3 class="sub-head">▸ Advice</h3>'
            f'<div class="sub-body">{md_to_html(tip.advice_md)}</div>'
            f'</section>'
        )
    if tip.technical_md:
        sections.append(
            f'<section class="subsection">'
            f'<h3 class="sub-head">▸ Technical Explanation</h3>'
            f'<div class="sub-body">{md_to_html(tip.technical_md)}</div>'
            f'</section>'
        )
    if tip.cta_md:
        sections.append(
            f'<section class="subsection cta">'
            f'<h3 class="sub-head">▸ Your Turn</h3>'
            f'<div class="sub-body">{md_to_html(tip.cta_md)}</div>'
            f'</section>'
        )
    if tip.sources_md:
        sections.append(
            f'<details class="tip-sources">'
            f'<summary>▸ Sources</summary>'
            f'<div class="sub-body">{md_to_html(tip.sources_md)}</div>'
            f'</details>'
        )
    body = "\n".join(sections)
    haystack = " ".join(
        [tip.title, tip.advice_md, tip.technical_md, tip.cta_md, tip.sources_md]
    ).lower()
    haystack = re.sub(r"\s+", " ", haystack)[:1500]
    return f'''
        <article id="{tip.slug}" class="card tip" data-tip="{tip.num:02d}" data-search="{html.escape(haystack)}">
          <header class="card-head">
            <span class="card-num">{tip.num:02d}</span>
            <h2>{html.escape(tip.title)}</h2>
            <a class="card-anchor" href="#{tip.slug}" aria-label="Link to tip {tip.num}">#</a>
          </header>
          <div class="card-body">
            {body}
          </div>
        </article>
    '''


def render_html(doc: ParsedDoc) -> str:
    title = html.escape(doc.title)
    intro_html = md_to_html(doc.intro_md)
    how_to_use_html = md_to_html(doc.how_to_use_md)
    tldr_html = tldr_with_links(doc.tldr_md, doc.tips)
    tips_html = "\n".join(render_tip(t) for t in doc.tips)
    anti_html = md_to_html(doc.anti_patterns_md)
    sources_html = md_to_html(doc.sources_md)
    sidebar = render_sidebar(doc)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="14 habits to ship better code with less spend on Claude Code. Every tip cites Anthropic docs, Boris Cherny, or a published field heuristic.">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="14 habits to ship better code with less spend on Claude Code.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://juanjofuchs.github.io/claude-code-tips/">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='10' fill='%231a1816'/%3E%3Ctext x='32' y='44' font-family='ui-monospace,monospace' font-size='34' font-weight='700' text-anchor='middle' fill='%23d97757'%3E%3E_%3C/text%3E%3C/svg%3E">
  <style>{CSS}</style>
</head>
<body>
  <a class="skip" href="#content">skip to content</a>
  <div class="layout">
    <aside class="sidebar" aria-label="Navigation">{sidebar}</aside>
    <main id="content" class="content">
      <header class="hero">
        <div class="terminal">
          <div class="terminal-bar">
            <span class="dot red" aria-hidden="true"></span>
            <span class="dot yellow" aria-hidden="true"></span>
            <span class="dot green" aria-hidden="true"></span>
            <span class="terminal-title">~ claude-code-tips</span>
          </div>
          <div class="terminal-body">
            <div class="prompt-line"><span class="prompt">$</span> <span class="cmd">claude --read claude-code-tips</span></div>
            <h1 class="hero-title">{title}</h1>
            <div class="hero-meta">
              {intro_html}
            </div>
            <div class="hero-actions">
              <a class="btn primary" href="#tldr">jump to tl;dr</a>
              <a class="btn" href="#tip-01">start at tip 01</a>
              <a class="btn ghost" href="https://github.com/JuanjoFuchs/claude-code-tips" target="_blank" rel="noopener">view on github ↗</a>
            </div>
          </div>
        </div>
      </header>

      <section id="how-to-use" class="card meta">
        <header class="card-head">
          <span class="card-num">$</span>
          <h2>How to use this guide</h2>
          <a class="card-anchor" href="#how-to-use" aria-label="Link to how to use">#</a>
        </header>
        <div class="card-body">{how_to_use_html}</div>
      </section>

      <section id="tldr" class="card tldr">
        <header class="card-head">
          <span class="card-num">$</span>
          <h2>TL;DR</h2>
          <a class="card-anchor" href="#tldr" aria-label="Link to TL;DR">#</a>
        </header>
        <div class="card-body">{tldr_html}</div>
      </section>

      <div id="tips" class="tips-stream">
        {tips_html}
      </div>

      <section id="anti-patterns" class="card warning">
        <header class="card-head">
          <span class="card-num warn">!</span>
          <h2>Anti-patterns</h2>
          <a class="card-anchor" href="#anti-patterns" aria-label="Link to anti-patterns">#</a>
        </header>
        <div class="card-body">{anti_html}</div>
      </section>

      <section id="sources" class="card sources">
        <header class="card-head">
          <span class="card-num">¶</span>
          <h2>Sources index</h2>
          <a class="card-anchor" href="#sources" aria-label="Link to sources">#</a>
        </header>
        <div class="card-body">{sources_html}</div>
      </section>

      <footer class="page-footer">
        <div class="prompt-line"><span class="prompt">$</span> <span class="muted">end of transmission — go build</span></div>
        <div class="footer-links">
          <a href="https://github.com/JuanjoFuchs/claude-code-tips" target="_blank" rel="noopener">github.com/JuanjoFuchs/claude-code-tips</a>
          <span class="sep">·</span>
          <a href="https://juanjofuchs.github.io/" target="_blank" rel="noopener">juanjofuchs.github.io</a>
        </div>
      </footer>
    </main>
  </div>
  <button id="empty-clear" class="empty-clear" hidden>clear filter</button>
  <script>{JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Inline CSS + JS (kept as separate strings for readability)
# ---------------------------------------------------------------------------


CSS = r"""
:root {
  --bg:           #1a1816;
  --bg-deep:      #0f0d0b;
  --bg-panel:     #221f1c;
  --bg-elev:      #2a2724;
  --fg:           #e8e3d8;
  --fg-strong:    #f3efe6;
  --fg-dim:       #9a948b;
  --fg-faint:     #5a5754;
  --accent:       #d97757;
  --accent-warm:  #e8a86b;
  --accent-soft:  rgba(217,119,87,0.12);
  --accent-line:  rgba(217,119,87,0.28);
  --warn:         #e8a857;
  --good:         #8aaa67;
  --border:       #2f2c28;
  --border-bright:#3f3b35;
  --link:         #e8a86b;
  --link-hover:   #f3c794;
  --font-mono: ui-monospace, SFMono-Regular, "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace;
  --shadow: 0 10px 40px rgba(0,0,0,0.4);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: var(--font-mono);
  font-size: 14.5px;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

a { color: var(--link); text-decoration: none; border-bottom: 1px solid transparent; transition: color .12s, border-color .12s; }
a:hover { color: var(--link-hover); border-bottom-color: var(--link-hover); }

.skip {
  position: absolute; left: -9999px; top: 0;
  background: var(--accent); color: var(--bg); padding: 8px 14px; z-index: 100;
}
.skip:focus { left: 8px; top: 8px; }

/* ---------- Layout ---------- */
.layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  max-width: 1320px;
  margin: 0 auto;
  min-height: 100vh;
}

/* ---------- Sidebar ---------- */
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  border-right: 1px solid var(--border);
  background: linear-gradient(180deg, var(--bg) 0%, var(--bg-deep) 100%);
  padding: 28px 22px 18px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-bright) transparent;
}
.sidebar::-webkit-scrollbar { width: 6px; }
.sidebar::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }

.sidebar-header { margin-bottom: 18px; }
.logo {
  color: var(--accent);
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.02em;
}
.logo::before { content: "▮ "; color: var(--accent-warm); }
.logo-sub {
  color: var(--fg-dim);
  font-size: 12px;
  margin-top: 4px;
  letter-spacing: 0.02em;
}

.search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-deep);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 22px;
  position: relative;
}
.search-wrap:focus-within { border-color: var(--accent-line); box-shadow: 0 0 0 1px var(--accent-line); }
.search-prompt { color: var(--accent); font-weight: 700; }
#search {
  flex: 1; min-width: 0;
  background: transparent;
  border: 0;
  color: var(--fg);
  font: inherit;
  outline: none;
  padding: 2px 0;
}
#search::placeholder { color: var(--fg-faint); }
.search-hint {
  font-size: 10px;
  color: var(--fg-faint);
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  white-space: nowrap;
  letter-spacing: 0.04em;
}

.toc { flex: 1; }
.toc-section-label {
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: lowercase;
  margin: 18px 0 8px;
}
.toc-section-label:first-child { margin-top: 0; }

.toc-list, .toc-extras { list-style: none; margin: 0; padding: 0; }
.toc-list li, .toc-extras li { margin: 0; }
.toc-list a, .toc-extras a {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
  border-bottom: 0;
  color: var(--fg-dim);
  font-size: 12.5px;
  line-height: 1.4;
  align-items: start;
}
.toc-list a:hover, .toc-extras a:hover {
  background: var(--bg-elev);
  color: var(--fg-strong);
}
.toc-list a.active, .toc-extras a.active {
  background: var(--accent-soft);
  color: var(--fg-strong);
  border-left: 2px solid var(--accent);
  padding-left: 6px;
}
.toc-num {
  color: var(--accent);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.toc-list li.is-hidden { display: none; }

.sidebar-footer {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--fg-faint);
  font-size: 11px;
  letter-spacing: 0.04em;
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--good);
  box-shadow: 0 0 8px var(--good);
  animation: pulse 2.4s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ---------- Main content ---------- */
.content {
  padding: 36px clamp(20px, 4vw, 56px) 80px;
  max-width: 920px;
  min-width: 0;
}

/* ---------- Hero ---------- */
.hero { margin-bottom: 36px; }
.terminal {
  border: 1px solid var(--border-bright);
  border-radius: 10px;
  background: linear-gradient(180deg, #1f1c19 0%, #1a1816 100%);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.terminal-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-deep);
  border-bottom: 1px solid var(--border);
  position: relative;
}
.dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.dot.red { background: #ff5f56; }
.dot.yellow { background: #ffbd2e; }
.dot.green { background: #27c93f; }
.terminal-title {
  position: absolute; left: 50%; transform: translateX(-50%);
  color: var(--fg-dim);
  font-size: 12px;
  letter-spacing: 0.04em;
}
.terminal-body { padding: 26px 28px 30px; }

.prompt-line { color: var(--fg-dim); font-size: 13px; margin-bottom: 14px; }
.prompt { color: var(--accent); font-weight: 700; margin-right: 8px; }
.cmd { color: var(--fg); }
.cmd::after {
  content: "▮";
  color: var(--accent);
  margin-left: 4px;
  animation: blink 1s steps(2) infinite;
}
@keyframes blink { 50% { opacity: 0; } }

.hero-title {
  font-family: var(--font-mono);
  font-size: clamp(28px, 4.4vw, 42px);
  line-height: 1.08;
  font-weight: 700;
  letter-spacing: -0.01em;
  margin: 0 0 16px;
  color: var(--fg-strong);
}
.hero-meta { color: var(--fg-dim); }
.hero-meta p { margin: 0 0 10px; }
.hero-meta strong { color: var(--fg); }

.hero-actions {
  display: flex; flex-wrap: wrap; gap: 10px;
  margin-top: 18px;
}
.btn {
  display: inline-flex; align-items: center;
  padding: 7px 14px;
  border: 1px solid var(--border-bright);
  border-radius: 6px;
  color: var(--fg);
  background: var(--bg-elev);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-bottom: 1px solid var(--border-bright);
  transition: transform .08s, background .12s, border-color .12s;
}
.btn:hover { background: var(--bg-panel); border-color: var(--accent-line); color: var(--fg-strong); border-bottom-color: var(--accent-line); }
.btn:active { transform: translateY(1px); }
.btn.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.btn.primary:hover { background: var(--accent-warm); color: var(--bg); border-color: var(--accent-warm); }
.btn.ghost { background: transparent; }

/* ---------- Cards ---------- */
.card {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  margin: 24px 0;
  overflow: hidden;
  transition: border-color .15s, box-shadow .15s;
}
.card:target,
.card:hover { border-color: var(--border-bright); }
.card:target { box-shadow: 0 0 0 1px var(--accent-line); }

.card-head {
  display: flex;
  align-items: baseline;
  gap: 14px;
  padding: 14px 20px;
  background: var(--bg-deep);
  border-bottom: 1px solid var(--border);
  position: relative;
}
.card-num {
  color: var(--accent);
  font-weight: 700;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border: 1px solid var(--accent-line);
  border-radius: 4px;
  background: var(--accent-soft);
  flex-shrink: 0;
}
.card-num.warn { color: var(--warn); border-color: rgba(232,168,87,0.32); background: rgba(232,168,87,0.10); }
.card-head h2 {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.005em;
  color: var(--fg-strong);
  flex: 1;
  min-width: 0;
}
.card-anchor {
  color: var(--fg-faint);
  font-size: 13px;
  border-bottom: 0;
  opacity: 0;
  transition: opacity .12s;
}
.card-head:hover .card-anchor { opacity: 1; }
.card-anchor:hover { color: var(--accent); }

.card-body { padding: 18px 20px 22px; }
.card-body p { margin: 0 0 12px; }
.card-body p:last-child { margin-bottom: 0; }
.card-body ul, .card-body ol { margin: 0 0 12px; padding-left: 22px; }
.card-body li { margin: 4px 0; }
.card-body li::marker { color: var(--accent); }
.card-body strong { color: var(--fg-strong); }
.card-body em { color: var(--fg); }

.card-body h3, .card-body h4 {
  font-family: var(--font-mono);
  font-size: 14px;
  margin: 18px 0 8px;
  color: var(--fg-strong);
}

.card-body blockquote {
  margin: 12px 0;
  padding: 10px 14px;
  border-left: 2px solid var(--accent);
  background: var(--accent-soft);
  color: var(--fg);
  border-radius: 0 6px 6px 0;
}
.card-body blockquote p:last-child { margin-bottom: 0; }

.card-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13px;
}
.card-body th, .card-body td {
  border: 1px solid var(--border-bright);
  padding: 6px 10px;
  text-align: left;
}
.card-body th { background: var(--bg-deep); color: var(--fg-strong); }

.card-body code {
  background: var(--bg-deep);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 92%;
  color: var(--accent-warm);
}

.card-body hr {
  border: 0;
  border-top: 1px dashed var(--border-bright);
  margin: 18px 0;
}

/* ---------- Subsections inside a tip ---------- */
.subsection { margin: 18px 0; }
.subsection:first-child { margin-top: 0; }
.sub-head {
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin: 0 0 8px;
}
.sub-body { color: var(--fg); }
.subsection.cta .sub-body {
  background: var(--accent-soft);
  border: 1px dashed var(--accent-line);
  border-radius: 6px;
  padding: 14px 16px;
}
.subsection.cta .sub-body p:last-child { margin-bottom: 0; }

/* ---------- Per-tip collapsible sources ---------- */
.tip-sources {
  margin: 18px 0 0;
  border-top: 1px dashed var(--border-bright);
  padding-top: 12px;
}
.tip-sources summary {
  cursor: pointer;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  list-style: none;
  user-select: none;
}
.tip-sources summary::-webkit-details-marker { display: none; }
.tip-sources summary::after { content: " ▾"; color: var(--fg-faint); }
.tip-sources[open] summary::after { content: " ▴"; }
.tip-sources summary:hover { color: var(--accent-warm); }
.tip-sources .sub-body { margin-top: 10px; }
.tip-sources .sub-body ul { margin: 0; padding-left: 18px; }
.tip-sources .sub-body li { color: var(--fg-dim); font-size: 13px; }

/* ---------- Code blocks (nested terminal frame) ---------- */
.code-frame {
  margin: 14px 0;
  border: 1px solid var(--border-bright);
  border-radius: 6px;
  background: var(--bg-deep);
  overflow: hidden;
}
.code-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: #15120f;
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--fg-dim);
}
.code-label { color: var(--accent); }
.code-copy {
  background: transparent;
  border: 1px solid var(--border-bright);
  color: var(--fg-dim);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background .12s, color .12s, border-color .12s;
}
.code-copy:hover { background: var(--bg-elev); color: var(--fg); border-color: var(--accent-line); }
.code-copy.ok { color: var(--good); border-color: rgba(138,170,103,0.4); }
.code-body {
  margin: 0;
  padding: 14px 16px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.55;
  color: var(--fg);
}
.code-body code { background: transparent; border: 0; padding: 0; color: inherit; }

/* ---------- Special cards ---------- */
.card.warning { border-color: rgba(232,168,87,0.28); }
.card.warning .card-head { background: rgba(232,168,87,0.06); }

.card.sources .card-body { columns: 2; column-gap: 36px; }
.card.sources .card-body ul { padding-left: 18px; break-inside: avoid; }
.card.sources .card-body h3 { break-after: avoid; margin-top: 0; }
@media (max-width: 820px) { .card.sources .card-body { columns: 1; } }

.card.tldr ol { padding-left: 24px; }
.card.tldr li { padding: 2px 0; }
.tldr-link {
  color: var(--fg);
  border-bottom: 0;
  display: block;
  padding: 4px 0;
}
.tldr-link:hover { color: var(--accent-warm); border-bottom: 0; }

/* hide cards filtered out by search */
.card.is-hidden { display: none; }
.tips-stream.is-filtered .card:not(.tip),
.tips-stream:not(.is-filtered) .empty-state { display: none; }
.empty-state {
  border: 1px dashed var(--border-bright);
  border-radius: 6px;
  padding: 24px;
  text-align: center;
  color: var(--fg-dim);
  margin: 24px 0;
}

/* ---------- Footer ---------- */
.page-footer {
  margin-top: 60px;
  padding-top: 24px;
  border-top: 1px dashed var(--border);
  color: var(--fg-faint);
  font-size: 12px;
}
.footer-links { margin-top: 6px; }
.footer-links a { color: var(--fg-dim); border-bottom: 0; }
.footer-links a:hover { color: var(--accent-warm); }
.footer-links .sep { margin: 0 8px; color: var(--fg-faint); }
.muted { color: var(--fg-dim); }

/* ---------- Floating clear filter ---------- */
.empty-clear {
  position: fixed; right: 18px; bottom: 18px;
  background: var(--accent); color: var(--bg);
  border: 0; border-radius: 999px;
  padding: 10px 16px; font-family: var(--font-mono); font-weight: 700;
  cursor: pointer; box-shadow: var(--shadow);
}
.empty-clear:hover { background: var(--accent-warm); }

/* ---------- Responsive ---------- */
@media (max-width: 920px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar {
    position: static; height: auto; max-height: none;
    border-right: 0; border-bottom: 1px solid var(--border);
    padding: 18px 16px;
  }
  .content { padding: 24px 18px 60px; }
  .terminal-body { padding: 20px 18px 22px; }
}

/* ---------- Print ---------- */
@media print {
  .sidebar, .empty-clear, .hero-actions, .card-anchor, .terminal-bar .dot { display: none; }
  body { background: #fff; color: #000; }
  .card { break-inside: avoid; border-color: #ccc; }
}
"""


JS = r"""
(function () {
  const search = document.getElementById('search');
  const tipsStream = document.getElementById('tips');
  const tipCards = Array.from(document.querySelectorAll('article.tip'));
  const tocLinks = Array.from(document.querySelectorAll('.toc a[href^="#"]'));
  const tocLinksByHash = new Map(tocLinks.map(a => [a.getAttribute('href'), a]));
  const tocTipItems = Array.from(document.querySelectorAll('.toc-list li[data-tip]'));
  const emptyClear = document.getElementById('empty-clear');

  // Build empty-state node lazily
  let emptyState = null;
  function ensureEmptyState() {
    if (emptyState) return emptyState;
    emptyState = document.createElement('div');
    emptyState.className = 'empty-state';
    emptyState.innerHTML = 'no tips match — <button id="empty-state-clear" style="background:transparent;color:var(--accent);border:0;font:inherit;cursor:pointer;text-decoration:underline">clear filter</button>';
    tipsStream.appendChild(emptyState);
    emptyState.querySelector('#empty-state-clear').addEventListener('click', () => {
      search.value = '';
      applyFilter('');
      search.focus();
    });
    return emptyState;
  }

  function applyFilter(raw) {
    const q = raw.trim().toLowerCase();
    let visible = 0;
    for (const card of tipCards) {
      const hay = card.dataset.search || '';
      const match = !q || hay.includes(q);
      card.classList.toggle('is-hidden', !match);
      if (match) visible++;
    }
    for (const li of tocTipItems) {
      const num = li.dataset.tip;
      const card = tipCards.find(c => c.dataset.tip === num);
      li.classList.toggle('is-hidden', !!q && card && card.classList.contains('is-hidden'));
    }
    tipsStream.classList.toggle('is-filtered', !!q);
    if (q && visible === 0) {
      ensureEmptyState();
      emptyState.style.display = '';
    } else if (emptyState) {
      emptyState.style.display = 'none';
    }
    emptyClear.hidden = !q;
  }

  if (search) {
    search.addEventListener('input', e => applyFilter(e.target.value));
    search.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        search.value = '';
        applyFilter('');
        search.blur();
      }
    });
  }
  if (emptyClear) {
    emptyClear.addEventListener('click', () => {
      search.value = '';
      applyFilter('');
      search.focus();
    });
  }

  // Global keyboard shortcuts: '/' focuses search, 'j'/'k' moves between tips
  document.addEventListener('keydown', e => {
    const tag = (e.target && e.target.tagName) || '';
    const typing = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable);
    if (e.key === '/' && !typing) {
      e.preventDefault();
      search && search.focus();
      return;
    }
    if (!typing && (e.key === 'j' || e.key === 'k' || e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      const dir = (e.key === 'j' || e.key === 'ArrowDown') ? 1 : -1;
      const visible = tipCards.filter(c => !c.classList.contains('is-hidden'));
      if (!visible.length) return;
      const y = window.scrollY + 100;
      let idx = 0;
      for (let i = 0; i < visible.length; i++) {
        if (visible[i].offsetTop <= y) idx = i;
      }
      const next = visible[Math.max(0, Math.min(visible.length - 1, idx + dir))];
      if (next) {
        e.preventDefault();
        next.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  });

  // Copy buttons on code blocks
  document.querySelectorAll('.code-copy').forEach(btn => {
    btn.addEventListener('click', async () => {
      const code = btn.closest('.code-frame').querySelector('code');
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code.innerText);
        const prev = btn.textContent;
        btn.textContent = '✓ copied';
        btn.classList.add('ok');
        setTimeout(() => { btn.textContent = prev; btn.classList.remove('ok'); }, 1400);
      } catch (err) {
        btn.textContent = 'press ^c';
        setTimeout(() => { btn.textContent = 'copy'; }, 1400);
      }
    });
  });

  // Scroll-spy: highlight the TOC entry of whichever card is in view
  const spyTargets = Array.from(document.querySelectorAll('.card[id], article.tip[id]'));
  const setActive = (id) => {
    tocLinks.forEach(a => a.classList.remove('active'));
    const link = tocLinksByHash.get('#' + id);
    if (link) link.classList.add('active');
  };
  if ('IntersectionObserver' in window && spyTargets.length) {
    const io = new IntersectionObserver((entries) => {
      const visible = entries
        .filter(e => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0] && visible[0].target.id) {
        setActive(visible[0].target.id);
      }
    }, { rootMargin: '-30% 0px -55% 0px', threshold: 0 });
    spyTargets.forEach(t => io.observe(t));
  }

  // Initialise the active link from the URL hash
  if (location.hash) setActive(location.hash.slice(1));
})();
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    if not README.exists():
        sys.stderr.write(f"error: README.md not found at {README}\n")
        return 1
    text = README.read_text(encoding="utf-8")
    doc = parse_readme(text)

    if not doc.tips:
        sys.stderr.write("error: no numbered tips parsed from README\n")
        return 2

    html_out = render_html(doc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(html_out, encoding="utf-8")

    print(f"  title:       {doc.title}")
    print(f"  tips parsed: {len(doc.tips)}")
    print(f"  tldr:        {'yes' if doc.tldr_md else 'no'}")
    print(f"  anti-pat:    {'yes' if doc.anti_patterns_md else 'no'}")
    print(f"  sources:     {'yes' if doc.sources_md else 'no'}")
    print(f"  output:      {OUT_FILE}  ({OUT_FILE.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
