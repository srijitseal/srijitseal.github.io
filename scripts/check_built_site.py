"""Check the generated homepage, local links, figures, and citation provenance."""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site"


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.references = []
        self.publication_ids = []
        self.citation_sources = []
        self.icon_classes = []
        self.meeting_links = []
        self.structured_data = []
        self.json_buffer = None
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = attrs.get("class", "").split()
        if tag == "i":
            self.icon_classes.append(classes)
        if "data-publication-id" in attrs:
            self.publication_ids.append(attrs["data-publication-id"])
        if "publication-citations" in classes:
            self.citation_sources.append(attrs)
        if "meeting-float" in classes:
            self.meeting_links.append(attrs.get("href"))
        if tag in ("img", "script", "source") and attrs.get("src"):
            self.references.append(attrs["src"])
        if tag in ("a", "link") and attrs.get("href"):
            self.references.append(attrs["href"])
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_buffer = ""

    def handle_data(self, data):
        if self.json_buffer is not None:
            self.json_buffer += data

    def handle_endtag(self, tag):
        if tag == "script" and self.json_buffer is not None:
            self.structured_data.append(json.loads(self.json_buffer))
            self.json_buffer = None


def local_target(reference, page_path):
    url = urlsplit(reference)
    if url.scheme or url.netloc or not url.path:
        return None
    path = unquote(url.path)
    return SITE / path.lstrip("/") if path.startswith("/") else page_path.parent / path


def exists_on_pages(path):
    return path.is_file() or (path / "index.html").is_file() or path.with_suffix(".html").is_file()


errors = []
home_text = (SITE / "index.html").read_text()
home = Page(home_text)
source_ids = re.findall(r"(?m)^- id:\s*(\S+)", (ROOT / "_data/publications.yml").read_text())
if home.publication_ids != source_ids:
    errors.append("Built publication IDs differ from the source list")
if "MCBIOS" in home_text or "mcbios-2026" in home_text:
    errors.append("MCBIOS is still present")
if "{{" in home_text or "{%" in home_text:
    errors.append("Unrendered Liquid in homepage")
if home.meeting_links != ["https://srijitseal.com/calendly"]:
    errors.append("Meeting button destination changed")
if not home.structured_data:
    errors.append("Structured metadata is missing")
for classes in home.icon_classes:
    if "fa-github" in classes and ("fab" not in classes or "fa" in classes):
        errors.append("GitHub icon must use the Brands font without the conflicting fa class")
for citation in home.citation_sources:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", citation.get("data-recorded", "")):
        errors.append("Citation badge has no observation date")
    if not any(source in citation.get("title", "") for source in ("Google Scholar", "OpenAlex")):
        errors.append("Citation badge has no source")

pages = [SITE / "index.html", SITE / "AIDDCourse.html", SITE / "media-kit/index.html", SITE / "tools.html"]
for page_path in pages:
    if not page_path.is_file():
        errors.append(f"Missing built page: {page_path.relative_to(SITE)}")
        continue
    page = Page(page_path.read_text())
    for reference in page.references:
        target = local_target(reference, page_path)
        if target and not exists_on_pages(target):
            errors.append(f"{page_path.relative_to(SITE)}: missing local target {reference}")

for filename in ("css/refresh.css", "js/publications.js", "webfonts/fa-solid-900.woff2", "webfonts/fa-regular-400.woff2", "webfonts/fa-brands-400.woff2"):
    if not (SITE / filename).is_file():
        errors.append(f"Missing deployed asset: {filename}")

if errors:
    raise SystemExit("\n".join(errors))
print(f"OK: {len(pages)} built pages, {len(source_ids)} publications, {len(home.citation_sources)} citation badges, and local links/assets.")
