#!/usr/bin/env python3
"""Refresh homepage live stats for the static Jekyll site.

The script intentionally uses only Python's standard library so it can run in
GitHub Actions without installing dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PUBLICATIONS_FILE = ROOT / "_data" / "publications.yml"
LIVE_STATS_FILE = ROOT / "_data" / "live_stats.yml"
PUBLICATION_METRICS_FILE = ROOT / "_data" / "publication_metrics.yml"
CONFIG_FILE = ROOT / "_config.yml"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def count_publications() -> int:
    text = read_text(PUBLICATIONS_FILE)
    return len(re.findall(r"(?m)^- id:\s+", text))


def clean_yaml_value(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        value = value[1:-1]
    return value.strip()


def yaml_line(block: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}:\s*(.+?)\s*$", block)
    if not match:
        return ""
    return clean_yaml_value(match.group(1))


def publications() -> list[dict[str, str]]:
    text = read_text(PUBLICATIONS_FILE)
    entries: list[dict[str, str]] = []
    for match in re.finditer(r"(?ms)^- id:\s*(.+?)\n(.*?)(?=^- id:\s|\Z)", text):
        block = match.group(2)
        pub_id = clean_yaml_value(match.group(1))
        title = yaml_line(block, "title")
        if not pub_id or not title:
            continue
        entries.append(
            {
                "id": pub_id,
                "title": title,
                "url": (
                    yaml_line(block, "OAlink")
                    or yaml_line(block, "Journal_notOA_link")
                    or yaml_line(block, "project_page")
                ),
            }
        )
    return entries


def config_value(key: str, default: str = "") -> str:
    text = read_text(CONFIG_FILE)
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
    if not match:
        return default
    return match.group(1).strip().strip('"').strip("'")


def previous_field(section: str, field: str, default: str = "") -> str:
    if not LIVE_STATS_FILE.exists():
        return default
    lines = read_text(LIVE_STATS_FILE).splitlines()
    in_section = False
    for line in lines:
        if line == f"{section}:":
            in_section = True
            continue
        if in_section and line and not line.startswith(" "):
            return default
        if in_section:
            match = re.match(rf"\s+{re.escape(field)}:\s*[\"']?(.+?)[\"']?\s*$", line)
            if match:
                return match.group(1).strip()
    return default


def previous_display(section: str, default: str = "updating") -> str:
    return previous_field(section, "display", default)


def previous_int(section: str) -> int | None:
    value = previous_field(section, "value")
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def previous_publication_metric(publication_id: str) -> dict[str, str]:
    if not PUBLICATION_METRICS_FILE.exists():
        return {}
    text = read_text(PUBLICATION_METRICS_FILE)
    match = re.search(rf"(?ms)^{re.escape(publication_id)}:\n((?:  .+\n)+)", text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        field_match = re.match(r"\s+([^:]+):\s*(.*?)\s*$", line)
        if field_match:
            fields[field_match.group(1)] = clean_yaml_value(field_match.group(2))
    return fields


def request_json(url: str, token: str | None = None) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "srijitseal.github.io live stats updater",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def github_stars(username: str) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    stars = 0
    page = 1
    while True:
        query = urllib.parse.urlencode({
            "type": "owner",
            "per_page": 100,
            "page": page,
        })
        repos = request_json(
            f"https://api.github.com/users/{urllib.parse.quote(username)}/repos?{query}",
            token=token,
        )
        if not repos:
            break
        stars += sum(int(repo.get("stargazers_count", 0)) for repo in repos)
        if len(repos) < 100:
            break
        page += 1
    return stars


def openalex_author() -> dict[str, Any] | None:
    explicit_id = os.environ.get("OPENALEX_AUTHOR_ID", "").strip()
    mailto = config_value("email")
    if explicit_id:
        author_id = explicit_id.rsplit("/", 1)[-1]
        query = urllib.parse.urlencode({"mailto": mailto}) if mailto else ""
        suffix = f"?{query}" if query else ""
        return request_json(f"https://api.openalex.org/authors/{author_id}{suffix}")

    params = {"search": config_value("name", "Srijit Seal"), "per-page": 10}
    if mailto:
        params["mailto"] = mailto
    data = request_json(f"https://api.openalex.org/authors?{urllib.parse.urlencode(params)}")
    candidates = data.get("results", [])
    if not candidates:
        return None

    normalized_name = config_value("name", "Srijit Seal").casefold()
    exact = [a for a in candidates if a.get("display_name", "").casefold() == normalized_name]
    pool = exact or candidates
    return max(pool, key=lambda a: int(a.get("cited_by_count", 0)))


def citation_count() -> int:
    author = openalex_author()
    if not author:
        raise RuntimeError("No OpenAlex author match found")
    return int(author.get("cited_by_count", 0))


def normalize_title(title: str) -> str:
    title = title.casefold()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def openalex_work_for_publication(publication: dict[str, str]) -> dict[str, Any] | None:
    mailto = config_value("email")
    params = {
        "search": publication["title"],
        "per-page": 5,
    }
    if mailto:
        params["mailto"] = mailto
    data = request_json(f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}")
    results = data.get("results", [])
    if not results:
        return None

    target_title = normalize_title(publication["title"])
    exact = [work for work in results if normalize_title(work.get("display_name", "")) == target_title]
    if exact:
        return max(exact, key=lambda work: int(work.get("cited_by_count", 0)))

    best = max(
        results,
        key=lambda work: (
            title_similarity(publication["title"], work.get("display_name", "")),
            int(work.get("cited_by_count", 0)),
        ),
    )
    if title_similarity(publication["title"], best.get("display_name", "")) < 0.72:
        return None
    return best


def publication_metrics() -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for index, publication in enumerate(publications()):
        try:
            work = openalex_work_for_publication(publication)
            if not work:
                raise RuntimeError("No OpenAlex work match found")
            citations = int(work.get("cited_by_count", 0))
            metrics[publication["id"]] = {
                "citations": citations,
                "display": format_int(citations),
                "source": "OpenAlex",
                "openalex_id": work.get("id", ""),
            }
        except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"warning: keeping previous citation metric for {publication['id']}: {exc}", file=sys.stderr)
            previous = previous_publication_metric(publication["id"])
            if previous:
                metrics[publication["id"]] = previous
        if index:
            time.sleep(0.1)
    return metrics


def format_int(value: int) -> str:
    return f"{value:,}"


def yaml_scalar(value: str | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_stats(stats: dict[str, dict[str, Any]], updated_at: datetime) -> None:
    updated_date = updated_at.strftime("%Y-%m-%d")
    updated_label = updated_at.strftime("%b %-d, %Y") if os.name != "nt" else updated_at.strftime("%b %#d, %Y")
    lines = []
    for section, values in stats.items():
        lines.append(f"{section}:")
        for key, value in values.items():
            lines.append(f"  {key}: {yaml_scalar(value)}")
    lines.append(f"updated_at: {yaml_scalar(updated_date)}")
    lines.append(f"updated_label: {yaml_scalar(updated_label)}")
    LIVE_STATS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_publication_metrics(metrics: dict[str, dict[str, Any]], updated_at: datetime) -> None:
    updated_date = updated_at.strftime("%Y-%m-%d")
    updated_label = updated_at.strftime("%b %-d, %Y") if os.name != "nt" else updated_at.strftime("%b %#d, %Y")
    lines = [
        "_meta:",
        f"  updated_at: {yaml_scalar(updated_date)}",
        f"  updated_label: {yaml_scalar(updated_label)}",
    ]
    for publication in publications():
        values = metrics.get(publication["id"])
        if not values:
            continue
        lines.append(f"{publication['id']}:")
        for key in ("citations", "display", "source", "openalex_id"):
            if key in values:
                lines.append(f"  {key}: {yaml_scalar(values[key])}")
    PUBLICATION_METRICS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    publication_count = count_publications()
    updated_at = datetime.now(ZoneInfo(os.environ.get("LIVE_STATS_TIMEZONE", "America/New_York")))

    try:
        citations = citation_count()
        citation_display = format_int(citations)
    except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"warning: keeping previous citation display: {exc}", file=sys.stderr)
        citations = previous_int("citations")
        citation_display = previous_display("citations")

    try:
        stars = github_stars(config_value("github_username", "srijitseal"))
        stars_display = format_int(stars)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"warning: keeping previous GitHub stars display: {exc}", file=sys.stderr)
        stars = previous_int("github_stars")
        stars_display = previous_display("github_stars")

    write_stats(
        {
            "publications": {
                "value": publication_count,
                "display": format_int(publication_count),
                "label": "Publications",
            },
            "citations": {
                "value": citations,
                "display": citation_display,
                "label": "Citations",
                "source": "OpenAlex",
            },
            "github_stars": {
                "value": stars,
                "display": stars_display,
                "label": "GitHub stars",
                "source": "GitHub",
            },
        },
        updated_at,
    )
    write_publication_metrics(publication_metrics(), updated_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
