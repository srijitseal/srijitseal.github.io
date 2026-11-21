"""Verify original public posts from Shares.csv without importing account data.

Previously verified public-page evidence is read from a local review directory.
This importer makes no network requests and uses no authenticated session,
messages, contacts, media downloads, or reactions-given exports.
"""

import argparse
from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from import_linkedin_analytics import ROOT, combine_snapshots, number, post_url


class PublicPostHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.documents = []
        self.json_text = None
        self.main = None
        self.in_main = False
        self.reshare = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_text = ""
        if tag == "article" and self.main is None and "main-feed-activity-card" in attrs.get("class", "").split():
            self.main = attrs
            self.in_main = True
        if self.in_main and attrs.get("data-test-id") == "feed-reshare-content":
            self.reshare = True

    def handle_data(self, data):
        if self.json_text is not None:
            self.json_text += data

    def handle_endtag(self, tag):
        if tag == "article":
            self.in_main = False
        if tag == "script" and self.json_text is not None:
            try:
                self.documents.append(json.loads(self.json_text))
            except json.JSONDecodeError:
                pass
            self.json_text = None


def identifier(url):
    matches = re.findall(r"(?:share:|ugcPost:|activity:|share-|activity-|ugcPost-)(\d{18,20})", unquote(url))
    return matches[-1] if matches else None


def source_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.linkedin.com" or parsed.query or parsed.fragment:
        raise ValueError("Only direct LinkedIn post URLs are accepted")
    if parsed.path.startswith("/posts/srijitseal_"):
        return post_url(url)
    if not re.fullmatch(r"/feed/update/urn:li:(share|ugcPost|activity):\d{18,20}/?", unquote(parsed.path)):
        raise ValueError("Unexpected export post URL")
    return url


def parse_public_post(html, requested_url):
    parser = PublicPostHTML()
    parser.feed(html)
    documents = []
    for item in parser.documents:
        documents.extend(item if isinstance(item, list) else item.get("@graph", [item]))
    candidates = [item for item in documents if isinstance(item, dict) and item.get("@type") == "SocialMediaPosting"]
    if len(candidates) != 1 or not parser.main:
        return {"status": "unverified", "reason": "No single public post and main article"}
    post = candidates[0]
    source_id = identifier(requested_url)
    page_ids = {identifier(post.get("@id", "")), identifier(parser.main.get("data-attributed-urn", "")),
                identifier(parser.main.get("data-activity-urn", ""))}
    if not source_id or source_id not in page_ids:
        return {"status": "unverified", "reason": "Page identity does not match the requested post"}
    author = post.get("author", {})
    author_url = urlsplit(author.get("url", ""))
    if author_url.netloc not in ("www.linkedin.com", "linkedin.com") or author_url.path.rstrip("/") != "/in/srijitseal":
        return {"status": "excluded", "reason": "Different author"}
    if parser.reshare or "sharedContent" in post or "isBasedOn" in post:
        return {"status": "excluded", "reason": "Repost or reshare with commentary", "canonical_url": post.get("@id")}
    try:
        canonical = post_url(post["@id"])
        published = datetime.fromisoformat(post["datePublished"].replace("Z", "+00:00")).date().isoformat()
    except (KeyError, ValueError):
        return {"status": "unverified", "reason": "Missing canonical URL or publication date"}
    body = post.get("articleBody", "").strip()
    if not body:
        return {"status": "excluded", "reason": "No authored post text"}
    reactions = None
    statistics = post.get("interactionStatistic", [])
    for stat in statistics if isinstance(statistics, list) else [statistics]:
        if stat.get("interactionType", "").rstrip("/").endswith("/LikeAction"):
            try:
                reactions = number(stat["userInteractionCount"])
            except (KeyError, ValueError):
                pass
    return {"status": "original", "canonical_url": canonical, "published_at": published,
            "headline": post.get("headline", ""), "text": body, "reactions": reactions}


def excerpt(text, limit):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def post_copy(record):
    paragraphs = [" ".join(part.split()) for part in record["text"].split("\n") if part.strip()]
    heading = " ".join((record.get("headline") or paragraphs[0]).split())
    title = excerpt(heading, 155)
    body = " ".join(paragraphs)
    remainder = body[len(heading):].strip() if body.startswith(heading) else body
    return title, excerpt(remainder, 280)


def merge_originals(data, records, observed_at):
    result = deepcopy(data)
    existing = {p["url"]: p for p in result["posts"]}
    excluded = {r.get("canonical_url", r["source_url"]) for r in records if r["status"] == "excluded"}
    for url in excluded:
        existing.pop(url, None)
    counts = Counter()
    for record in records:
        if record["status"] != "original":
            continue
        url = post_url(record["canonical_url"])
        post = existing.get(url)
        if post is None:
            title, summary = post_copy(record)
            post = {"id": "linkedin-" + identifier(url), "title": title, "summary": summary,
                    "topic": "Posts", "url": url, "published_at": record["published_at"],
                    "reactions": None, "reactions_observed_at": None, "impression_snapshots": {}}
            existing[url] = post
            counts["added"] += 1
        else:
            counts["matched"] += 1
        current = post.get("reactions")
        incoming = record.get("reactions")
        if incoming is not None and (current is None or incoming >= current):
            post["reactions"] = number(incoming)
            post["reactions_observed_at"] = record.get("observed_at", observed_at)
    result["posts"] = sorted(existing.values(), key=lambda p: p["published_at"], reverse=True)
    evidence_dates = [r.get("observed_at", observed_at) for r in records if r["status"] in ("original", "excluded")]
    result["snapshot_date"] = max([result["snapshot_date"], *evidence_dates])
    combine_snapshots(result)
    counts["removed_reshares"] = len(data["posts"]) - sum(p["url"] in existing for p in data["posts"])
    return result, dict(counts)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("shares", type=Path)
    args.add_argument("--review-dir", type=Path, required=True)
    args.add_argument("--data", type=Path, default=ROOT / "_data/linkedin.json")
    args.add_argument("--since", default="2024-01-01")
    args.add_argument("--apply", action="store_true")
    options = args.parse_args()
    review = options.review_dir.resolve()
    if review == ROOT or ROOT in review.parents:
        raise ValueError("Keep the review cache outside the website repository")
    review.mkdir(mode=0o700, parents=True, exist_ok=True)
    observed = datetime.now(timezone.utc).date().isoformat()
    data = json.loads(options.data.read_text())
    queue = {}
    skipped = Counter()
    with options.shares.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["Date", "ShareLink", "ShareCommentary", "SharedUrl", "MediaUrl", "Visibility"]:
            raise ValueError("Unexpected Shares.csv columns")
        for row in reader:
            published = datetime.strptime(row["Date"], "%Y-%m-%d %H:%M:%S").date().isoformat()
            if published < options.since:
                skipped["outside_date_range"] += 1
            elif not row["ShareCommentary"].strip():
                skipped["no_authored_text"] += 1
            elif unquote(urlsplit(row["ShareLink"]).path).startswith("/feed/update/urn:li:groupPost:"):
                skipped["group_post"] += 1
            else:
                queue[source_url(row["ShareLink"])] = published
    for post in data["posts"]:
        queue.setdefault(source_url(post["url"]), post["published_at"])
    records = []
    for url, expected_date in queue.items():
        cache = review / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        record = json.loads(cache.read_text()) if cache.exists() else None
        if not record or record.get("parser_version") != 2:
            continue
        if record.get("source_url") != url:
            raise ValueError("Review evidence does not match its source URL")
        if record["status"] == "original" and record["published_at"] != expected_date:
            raise ValueError("Public date differs from export date")
        records.append(record)
    result, changes = merge_originals(data, records, observed)
    summary = {"checked": len(records), "queued": len(queue), "skipped_export_rows": dict(skipped), "statuses": dict(Counter(r["status"] for r in records)),
               "reasons": dict(Counter(r["reason"] for r in records if r.get("reason"))),
               "changes": changes, "archive_posts": len(result["posts"]), "indices": result["post_indices"]["all"]}
    (review / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if options.apply:
        options.data.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
