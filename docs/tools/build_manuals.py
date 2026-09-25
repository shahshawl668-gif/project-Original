"""Render the markdown manuals as PDFs a client can actually be sent.

A manual in the repository is for whoever is editing it. A manual going to a
client's payroll team has to carry its own screenshots, paginate, and look like
something a company produced. This turns one into the other.

    python docs/tools/build_manuals.py [outdir]

Chromium does the rendering, so the PDF matches what the browser shows and
there is no second layout engine to disagree with it. Images are embedded as
data URIs rather than linked, because a PDF that depends on files next to it is
a PDF that arrives broken.
"""
from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent.parent
REPO = DOCS.parent

#: Title and audience are printed on the cover, so each PDF says who it is for.
MANUALS = [
    ("CLIENT_USER_MANUAL.md", "User Manual",
     "For payroll, HR and finance staff at a client company"),
    ("IMPLEMENTATION_MANUAL.md", "Implementation Manual",
     "For whoever sets up a new client"),
    ("ADMIN_MANUAL.md", "Administrator Manual",
     "For the team running the platform"),
    ("GO_LIVE.md", "Go-Live Runbook",
     "Internal — the gates before the first paying client"),
]

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
@page :first { margin-top: 0; }
* { box-sizing: border-box; }
body {
  font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  font-size: 10.5pt; line-height: 1.55; color: #16242e; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.cover {
  height: 247mm; display: flex; flex-direction: column; justify-content: center;
  padding: 0 4mm; page-break-after: always;
}
.cover .mark {
  font-size: 9pt; letter-spacing: .22em; text-transform: uppercase;
  color: #0369a1; font-weight: 600; margin-bottom: 14mm;
}
.cover h1 {
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 30pt; line-height: 1.1; margin: 0 0 6mm; color: #0c4a6e; font-weight: 600;
}
.cover .aud { font-size: 12pt; color: #47616f; margin: 0 0 18mm; }
.cover .rule { height: 3px; width: 52mm; background: #0284c7; margin-bottom: 8mm; }
.cover .foot { font-size: 9pt; color: #6d8595; line-height: 1.7; }
.cover .foot b { color: #47616f; font-weight: 500; }

h1, h2, h3, h4 { font-family: "IBM Plex Serif", Georgia, serif; color: #0c4a6e; page-break-after: avoid; }
h1 { font-size: 19pt; margin: 0 0 4mm; }
h2 {
  font-size: 15pt; margin: 9mm 0 3mm; padding-bottom: 2mm;
  border-bottom: 1px solid #d6e3ec; page-break-before: auto;
}
h3 { font-size: 12pt; margin: 6mm 0 2mm; }
h4 { font-size: 10.5pt; margin: 5mm 0 2mm; }
p { margin: 0 0 3mm; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; }
li { margin-bottom: 1.4mm; }
strong { color: #0f1b24; }
a { color: #0369a1; text-decoration: none; }
hr { border: none; border-top: 1px solid #e2ecf3; margin: 7mm 0; }

code {
  font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 9pt;
  background: #eef4f9; padding: 0.5mm 1.2mm; border-radius: 2px; color: #0c4a6e;
}
pre {
  background: #eff4f8; border: 1px solid #d6e3ec; border-radius: 3px;
  padding: 3mm 4mm; overflow-x: auto; page-break-inside: avoid;
}
pre code { background: none; padding: 0; font-size: 8.6pt; line-height: 1.5; }

table {
  border-collapse: collapse; width: 100%; margin: 0 0 4mm;
  font-size: 9.2pt; page-break-inside: avoid;
}
th {
  background: #0c4a6e; color: #fff; text-align: left; font-weight: 600;
  padding: 2mm 2.5mm; font-size: 8.4pt; text-transform: uppercase; letter-spacing: .05em;
}
td { padding: 2mm 2.5mm; border-bottom: 1px solid #e2ecf3; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafc; }

img {
  max-width: 100%; height: auto; display: block; margin: 4mm auto;
  border: 1px solid #d6e3ec; border-radius: 3px; page-break-inside: avoid;
}
blockquote {
  margin: 0 0 4mm; padding: 3mm 4mm; background: #eef7fd;
  border-left: 3px solid #0284c7; page-break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }
h2 + p, h3 + p { margin-top: 0; }

.toc { page-break-after: always; }
.toc h2 { border-bottom: none; margin-top: 0; }
/* The manuals number their own sections, so the list must not number them
   again — "1  1. What this does for you" reads as a mistake. */
.toc ol { list-style: none; padding: 0; margin: 0; }
.toc li { margin: 0; }
.toc a {
  display: block; padding: 2.4mm 0; border-bottom: 1px dotted #d6e3ec;
  color: #16242e; font-size: 10.5pt;
}
"""

HEADER = """
<div style="font-size:7pt;color:#8aa0b0;width:100%;padding:0 16mm;
            font-family:'IBM Plex Sans',sans-serif;">
  <span style="float:left;">{title}</span>
  <span style="float:right;">Peopleopslab</span>
</div>
"""

FOOTER = """
<div style="font-size:7pt;color:#8aa0b0;width:100%;padding:0 16mm;
            font-family:'IBM Plex Sans',sans-serif;text-align:center;">
  <span class="pageNumber"></span> of <span class="totalPages"></span>
</div>
"""


def embed_images(html: str) -> tuple[str, int]:
    """Inline every local image. A PDF that needs files beside it arrives broken."""
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        src = m.group(2)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        path = (DOCS / src).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"manual references a missing image: {src}")
        data = base64.b64encode(path.read_bytes()).decode()
        count += 1
        return f'{m.group(1)}data:image/png;base64,{data}"'

    return re.sub(r'(<img[^>]*\ssrc=")([^"]+)"', repl, html), count


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def build(outdir: Path) -> list[Path]:
    from datetime import date
    from playwright.sync_api import sync_playwright

    outdir.mkdir(parents=True, exist_ok=True)
    commit = git_commit()
    today = date.today().strftime("%d %B %Y")
    written: list[Path] = []

    md = markdown.Markdown(extensions=["tables", "fenced_code", "attr_list",
                                       "sane_lists", "toc"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        page = browser.new_page()

        for filename, title, audience in MANUALS:
            source = DOCS / filename
            if not source.is_file():
                print(f"  skipped {filename} (not found)")
                continue

            md.reset()
            body = md.convert(source.read_text())
            # The markdown's own H1 duplicates the cover, so drop the first one.
            # It carries an id once the toc extension is on, so match attributes.
            body = re.sub(r"<h1\b[^>]*>.*?</h1>", "", body, count=1, flags=re.S)
            body, images = embed_images(body)

            # A manual people look things up in needs a way in. Only the
            # top-level sections: a contents list that mirrors every heading is
            # a second document, not a route through the first.
            entries = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body, flags=re.S)
            contents = ""
            if len(entries) >= 3:
                rows = "".join(
                    f'<li><a href="#{anchor}">{re.sub(r"<[^>]+>", "", text).strip()}</a></li>'
                    for anchor, text in entries
                )
                contents = f'<div class="toc"><h2>Contents</h2><ol>{rows}</ol></div>' 

            cover = f"""
            <div class="cover">
              <div class="mark">Peopleopslab · India · Audit grade</div>
              <div class="rule"></div>
              <h1>{title}</h1>
              <p class="aud">{audience}</p>
              <div class="foot">
                <b>Version</b> {commit}<br>
                <b>Issued</b> {today}<br>
                <b>Source</b> docs/{filename}
              </div>
            </div>
            """

            html = (f'<html><head><meta charset="utf-8">'
                    f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
                    f'family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&'
                    f'family=IBM+Plex+Mono:wght@400&display=swap">'
                    f"<style>{CSS}</style></head><body>{cover}{contents}{body}</body></html>")

            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(1200)   # let the webfonts settle before measuring

            out = outdir / (filename.replace(".md", "").lower().replace("_", "-") + ".pdf")
            page.pdf(path=str(out), format="A4", print_background=True,
                     display_header_footer=True,
                     header_template=HEADER.format(title=title),
                     footer_template=FOOTER,
                     margin={"top": "18mm", "bottom": "20mm",
                             "left": "16mm", "right": "16mm"})
            size = out.stat().st_size / 1024
            print(f"  {out.name:<34} {size:6.0f}K  ({images} images embedded)")
            written.append(out)

        browser.close()
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DOCS / "pdf"
    files = build(target)
    print(f"\n{len(files)} manual(s) written to {target}")
