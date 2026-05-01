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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PUBLICATIONS_FILE = ROOT / "_data" / "publications.yml"
LIVE_STATS_FILE = ROOT / "_data" / "live_stats.yml"
CONFIG_FILE = ROOT / "_config.yml"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def count_publications() -> int:
    text = read_text(PUBLICATIONS_FILE)
    return len(re.findall(r"(?m)^- id:\s+", text))


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


def main() -> int:
    publications = count_publications()

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
                "value": publications,
                "display": format_int(publications),
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
        datetime.now(ZoneInfo(os.environ.get("LIVE_STATS_TIMEZONE", "America/New_York"))),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
