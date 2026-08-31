"""Deterministic Markdown-to-HTML rendering for Production Support Runbooks."""

from __future__ import annotations

import logging
from pathlib import Path
import markdown

LOGGER = logging.getLogger(__name__)

# Embedded standalone CSS for professional, readable offline rendering in Chrome/Edge
STANDALONE_CSS = """
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  --color-bg: #f8fafc;
  --color-surface: #ffffff;
  --color-text: #1e293b;
  --color-text-muted: #64748b;
  --color-heading: #0f172a;
  --color-border: #e2e8f0;
  --color-border-dark: #cbd5e1;
  --color-primary-bg: #eff6ff;
  --color-primary-border: #3b82f6;
  --color-primary-text: #1e40af;
  --color-code-bg: #f1f5f9;
  --color-pre-bg: #0f172a;
  --color-pre-text: #f8fafc;
}

*, *::before, *::after {
  box-sizing: border-box;
}

body {
  margin: 0;
  padding: 2rem 1rem;
  background-color: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.6;
}

.runbook-container {
  max-width: 960px;
  margin: 0 auto;
  background: var(--color-surface);
  padding: 2.5rem 3rem;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
  border: 1px solid var(--color-border);
}

h1, h2, h3, h4, h5, h6 {
  color: var(--color-heading);
  font-weight: 600;
  line-height: 1.3;
  margin-top: 1.75rem;
  margin-bottom: 0.75rem;
}

h1 {
  font-size: 1.85rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid var(--color-border);
  margin-top: 0;
}

h2 {
  font-size: 1.35rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--color-border);
  margin-top: 2rem;
}

h3 {
  font-size: 1.15rem;
}

p {
  margin-top: 0;
  margin-bottom: 1rem;
}

ul, ol {
  margin-top: 0;
  margin-bottom: 1rem;
  padding-left: 1.75rem;
}

li {
  margin-bottom: 0.35rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.25rem 0;
  font-size: 0.92rem;
  overflow-x: auto;
  display: block;
}

th, td {
  border: 1px solid var(--color-border-dark);
  padding: 0.6rem 0.85rem;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}

th {
  background-color: var(--color-code-bg);
  font-weight: 600;
  color: var(--color-heading);
}

tr:nth-child(even) {
  background-color: #f8fafc;
}

code {
  font-family: var(--font-mono);
  font-size: 0.88em;
  background-color: var(--color-code-bg);
  color: #0f172a;
  padding: 0.2em 0.4em;
  border-radius: 4px;
  border: 1px solid var(--color-border);
}

pre {
  background-color: var(--color-pre-bg);
  color: var(--color-pre-text);
  padding: 1rem 1.25rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: 1rem 0;
}

pre code {
  background: transparent;
  color: inherit;
  padding: 0;
  border: none;
  font-size: 0.9em;
}

blockquote {
  margin: 1.25rem 0;
  padding: 0.75rem 1.25rem;
  background-color: var(--color-primary-bg);
  border-left: 4px solid var(--color-primary-border);
  color: var(--color-primary-text);
  border-radius: 0 4px 4px 0;
}

blockquote p:last-child {
  margin-bottom: 0;
}

hr {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 2rem 0;
}

a {
  color: #2563eb;
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
}
"""


def render_body(markdown_text: str) -> str:
    """
    Deterministically convert Markdown text to clean HTML body.
    Supports tables, fenced code blocks, sane lists, inline formatting, blockquotes, and links.
    Does NOT wrap in <html>/<head>/<body> tags.
    """
    if not markdown_text:
        return ""

    html_content = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    return html_content


def render_document(markdown_text: str, title: str = "") -> str:
    """
    Convert Markdown text to a complete standalone HTML document suitable for opening locally in Chrome/Edge.
    Includes UTF-8 meta, viewport meta, document title, and embedded CSS styling.
    """
    body_html = render_body(markdown_text)
    page_title = title.strip() if title and title.strip() else "Production Support Runbook"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <style>
{STANDALONE_CSS}
  </style>
</head>
<body>
  <div class="runbook-container">
{body_html}
  </div>
</body>
</html>
"""


def generate_runbook_html(
    runbook_path: Path | str,
    output_dir: Path | str,
    repo_name: str = "",
    service_name: str = "",
) -> Path:
    """
    Deterministically generate RUNBOOK.html in output_dir from validated RUNBOOK.md.
    RUNBOOK.md is read-only and remains byte-for-byte untouched.
    """
    rb_path = Path(runbook_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not rb_path.exists() or not rb_path.is_file():
        raise FileNotFoundError(f"Runbook file not found at {rb_path}")

    markdown_content = rb_path.read_text(encoding="utf-8")

    # Construct human-friendly document title
    doc_title = repo_name or service_name
    if doc_title:
        title = f"{doc_title} - Production Support Runbook"
    else:
        title = "Production Support Runbook"

    standalone_html = render_document(markdown_content, title=title)
    html_target = out_dir / "RUNBOOK.html"
    html_target.write_text(standalone_html, encoding="utf-8")

    LOGGER.info("Generated standalone HTML runbook at %s", html_target)
    return html_target
