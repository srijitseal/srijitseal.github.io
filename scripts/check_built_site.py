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
        self.publication_attributes = {}
        self.images = {}
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
            self.publication_attributes[attrs["data-publication-id"]] = attrs
        if tag == "img" and attrs.get("src"):
            self.images[attrs["src"]] = attrs
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
illustrations = {
    "vsa_explainer": "vsa_explainer_illustration.png",
    "adme_ml_chapter": "adme_ml_illustration.png",
    "medchem_map_dl": "medchem_deep_learning_illustration.png",
}
for publication_id, filename in illustrations.items():
    attrs = home.publication_attributes.get(publication_id, {})
    if not attrs.get("data-image-credit", "").startswith("AI-generated illustration"):
        errors.append(f"{publication_id}: missing illustration provenance")
    if attrs.get("data-image-source"):
        errors.append(f"{publication_id}: illustration must not be attributed to a paper figure")
    image = home.images.get(f"./images/{filename}", {})
    if not image.get("alt", "").startswith("Conceptual illustration"):
        errors.append(f"{publication_id}: missing illustration or descriptive alt text")
for classes in home.icon_classes:
    if "fa-github" in classes and ("fab" not in classes or "fa" in classes):
        errors.append("GitHub icon must use the Brands font without the conflicting fa class")
for citation in home.citation_sources:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", citation.get("data-recorded", "")):
        errors.append("Citation badge has no observation date")
    if not any(source in citation.get("title", "") for source in ("Google Scholar", "OpenAlex")):
        errors.append("Citation badge has no source")

pages = [SITE / "index.html", SITE / "AIDDCourse.html", SITE / "media-kit/index.html", SITE / "tools.html", SITE / "linkedin/index.html"]
for page_path in pages:
    if not page_path.is_file():
        errors.append(f"Missing built page: {page_path.relative_to(SITE)}")
        continue
    page = Page(page_path.read_text())
    for reference in page.references:
        target = local_target(reference, page_path)
        if target and not exists_on_pages(target):
            errors.append(f"{page_path.relative_to(SITE)}: missing local target {reference}")

for filename in ("css/refresh.css", "js/publications.js", "css/linkedin.css", "js/linkedin.js", "webfonts/fa-solid-900.woff2", "webfonts/fa-regular-400.woff2", "webfonts/fa-brands-400.woff2"):
    if not (SITE / filename).is_file():
        errors.append(f"Missing deployed asset: {filename}")

linkedin_path = SITE / "linkedin/index.html"
if linkedin_path.is_file():
    linkedin_text = linkedin_path.read_text()
    snapshot = json.loads((ROOT / "_data/linkedin.json").read_text())
    if "{{" in linkedin_text or "{%" in linkedin_text:
        errors.append("Unrendered Liquid in LinkedIn archive")
    if len(re.findall(r'data-post-id=', linkedin_text)) != len(snapshot["posts"]):
        errors.append("LinkedIn post count differs from the snapshot")
    for post in snapshot["posts"]:
        if post["url"] not in linkedin_text:
            errors.append(f"Missing LinkedIn post: {post['id']}")
    month_count = len(snapshot["combined"]["monthly_impressions"]) + sum(len(year.get("monthly_impressions", [])) for year in snapshot["years"].values())
    if len(re.findall(r'class="chart-column', linkedin_text)) != month_count:
        errors.append("LinkedIn chart does not contain every month")
    panel_years = re.findall(r'class="year-snapshot" data-year="([^"]*)"', linkedin_text)
    if sorted(panel_years) != sorted(["all", *snapshot["years"]]):
        errors.append("LinkedIn year panels are missing or duplicated")
    for attribute, key in (("h-all", "h_index"), ("i10-all", "i10_index")):
        expected = f'data-index="{attribute}">{snapshot["post_indices"]["all"][key]}</td>'
        if linkedin_text.count(expected) != len(panel_years):
            errors.append(f"Missing or incorrect reaction index: {key}")
    if "not academic citations" not in linkedin_text or 'class="chart-gridline"' not in linkedin_text:
        errors.append("LinkedIn indices lack their scope or chart scale")
    for warning in ("snapshots, not live", "Reactions include likes", "Period totals cover all posts", "lower bound"):
        if warning not in linkedin_text:
            errors.append(f"Missing LinkedIn metric definition: {warning}")

if errors:
    raise SystemExit("\n".join(errors))
print(f"OK: {len(pages)} built pages, {len(source_ids)} publications, {len(home.citation_sources)} citation badges, and local links/assets.")
