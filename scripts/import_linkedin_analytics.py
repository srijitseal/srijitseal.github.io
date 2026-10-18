"""Import aggregate/post impressions from an owner-provided LinkedIn XLSX export.

Only the requested metrics enter the public JSON. Demographics and account data
are never read. Post titles and reaction counts are maintained separately.
"""

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def number(value):
    text = str(value).replace(",", "")
    if not text.isdigit():
        raise ValueError(f"Expected a nonnegative whole number, got {value!r}")
    return int(text)


def export_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def post_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != "www.linkedin.com" or not parsed.path.startswith("/posts/srijitseal_"):
        raise ValueError(f"Unexpected LinkedIn post URL: {value}")
    return value


def reaction_indices(posts):
    counts = sorted((number(post["reactions"]) for post in posts), reverse=True)
    return {
        "posts": len(counts), "reactions": sum(counts),
        "h_index": max((rank for rank, count in enumerate(counts, 1) if count >= rank), default=0),
        "i10_index": sum(count >= 10 for count in counts),
    }


def chart_scale(months):
    maximum = max((number(month["impressions"]) for month in months), default=0)
    raw_step = max(maximum / 4, 1)
    power = 10 ** math.floor(math.log10(raw_step))
    step = next(size * power for size in (1, 2, 2.5, 5, 10) if size * power >= raw_step)
    ceiling = max(1, math.ceil(maximum / step)) * step
    return {
        "maximum": int(ceiling),
        "ticks": [{"value": int(value * step), "label": f"{int(value * step):,}", "position": value * step / ceiling * 100}
                  for value in range(round(ceiling / step), -1, -1)],
    }


def combine_snapshots(data):
    """Add disjoint reporting periods, never deduplicated audience counts."""
    recent_year = data.get("snapshot_date", max((p["published_at"] for p in data["posts"]), default="2026"))[:4]
    data["post_indices"] = {
        "all": reaction_indices(data["posts"]), "recent_year": recent_year,
        "recent": reaction_indices([p for p in data["posts"] if p["published_at"][:4] >= recent_year]),
        "years": {year: reaction_indices([p for p in data["posts"] if p["published_at"][:4] == year]) for year in data["years"]},
    }
    snapshots = sorted((s for s in data["years"].values() if s.get("period")), key=lambda s: s["period"]["start"])
    if not snapshots:
        data["combined"] = {"period": None}
        return
    for previous, current in zip(snapshots, snapshots[1:]):
        if previous["period"]["end"] >= current["period"]["start"]:
            raise ValueError("Cannot combine overlapping export periods")
    reactions = [s["totals"].get("reactions") for s in snapshots]
    dates = [s.get("reactions_observed_at") for s in snapshots]
    data["combined"] = {
        "period": {"start": snapshots[0]["period"]["start"], "end": snapshots[-1]["period"]["end"]},
        "periods": [s["period"] for s in snapshots],
        "observed_at": max(s["observed_at"] for s in snapshots),
        "reactions_observed_at": max(dates) if all(dates) else None,
        "totals": {
            "impressions": sum(s["totals"]["impressions"] for s in snapshots),
            "reactions": sum(reactions) if all(r is not None for r in reactions) else None,
            "members_reached": None,
            "followers": snapshots[-1]["totals"]["followers"],
        },
        "monthly_impressions": [m for s in snapshots for m in s["monthly_impressions"]],
    }
    for snapshot in [*snapshots, data["combined"]]:
        snapshot["chart_scale"] = chart_scale(snapshot["monthly_impressions"])
    for post in data["posts"]:
        relevant = [s for s in snapshots if post["published_at"] <= s["period"]["end"]]
        metrics = [post.get("impression_snapshots", {}).get(s["period"]["start"][:4], {}) for s in relevant]
        known = [m["impressions"] for m in metrics if m.get("impressions") is not None]
        post["impressions"] = sum(known) if known else None
        post["impressions_is_partial"] = bool(known) and len(known) < len(relevant)
        post["impressions_period"] = data["combined"]["period"]
        post["impressions_observed_at"] = max((m["observed_at"] for m in metrics if m.get("observed_at")), default=None)


def import_metrics(data, sheets, observed_at, reactions=None):
    result = deepcopy(data)
    observed = date.fromisoformat(observed_at)
    discovery = dict(sheets["DISCOVERY"])
    start, end = [export_date(part.strip()) for part in discovery["Overall Performance"].split(" - ")]
    period = {"start": start, "end": end}
    if start > end or end > observed.isoformat():
        raise ValueError("The export period must end on or before the observation date")
    if start[:4] != end[:4]:
        raise ValueError("Select exactly one calendar year per export")
    year = start[:4]
    previous = result["years"].get(year, {})
    snapshot = {
        "period": period, "observed_at": observed_at,
        "totals": {"reactions": None}, "reactions_observed_at": None,
        "monthly_impressions": [],
    }
    monthly = defaultdict(int)
    days = set()
    daily_rows = sheets["ENGAGEMENT"]
    if tuple(daily_rows[0][:3]) != ("Date", "Impressions", "Engagements"):
        raise ValueError("Unexpected ENGAGEMENT headers")
    for day, impressions, _engagements in daily_rows[1:]:
        day = export_date(day)
        if not start <= day <= end or day in days:
            raise ValueError("Duplicate or out-of-range daily metric")
        days.add(day)
        monthly[day[:7]] += number(impressions)
    expected_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if len(days) != expected_days:
        raise ValueError("The export does not contain every day in its period")
    total = number(discovery["Impressions"])
    if sum(monthly.values()) != total:
        raise ValueError("Daily impressions do not match the export total")
    for month, count in sorted(monthly.items()):
        first = date.fromisoformat(month + "-01")
        following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = following - timedelta(days=1)
        snapshot["monthly_impressions"].append({
            "month": month, "impressions": count,
            "partial": first.isoformat() < start or last.isoformat() > end,
        })
    follower_label, followers = sheets["FOLLOWERS"][0]
    if not follower_label.startswith("Total followers on ") or export_date(follower_label.removeprefix("Total followers on ")) != end:
        raise ValueError("Follower count date does not match the export")
    snapshot["totals"].update(impressions=total, members_reached=number(discovery["Members reached"]), followers=number(followers))
    # Engagements include more than reactions. Never use them as likes.
    if reactions is not None:
        snapshot["totals"]["reactions"] = number(reactions)
        snapshot["reactions_observed_at"] = observed_at
    elif previous.get("period") == period:
        snapshot["totals"]["reactions"] = previous["totals"].get("reactions")
        snapshot["reactions_observed_at"] = previous.get("reactions_observed_at")
    result["years"][year] = snapshot
    result["snapshot_date"] = max(result.get("snapshot_date", observed_at), observed_at)
    rows = sheets["TOP POSTS"]
    if tuple(rows[2][4:7]) != ("Post URL", "Post Publish Date", "Impressions"):
        raise ValueError("Unexpected TOP POSTS headers")
    metrics = {}
    for row in rows[3:]:
        url, published, impressions = row[4:7]
        if not url:
            continue
        url = post_url(url)
        if url in metrics:
            raise ValueError("Duplicate post URL in impression rankings")
        metrics[url] = (export_date(published), number(impressions))
    for post in result["posts"]:
        post_url(post["url"])
        if "published_at" not in post:
            raise ValueError(f"No publication date for {post['id']}")
        if post["url"] in metrics:
            published, impressions = metrics[post["url"]]
            if post.get("published_at", published) != published:
                raise ValueError(f"Publication date changed for {post['id']}")
            count = impressions
        else:
            count = None
        post.setdefault("impression_snapshots", {})[year] = {
            "impressions": count, "period": period, "observed_at": observed_at,
        }
    combine_snapshots(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--observed-at", required=True, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--reactions", type=int, help="Manually verified total for exactly the exported period")
    parser.add_argument("--data", type=Path, default=ROOT / "_data/linkedin.json")
    args = parser.parse_args()
    from openpyxl import load_workbook
    with args.data.open() as source:
        data = json.load(source)
    workbook = load_workbook(args.export, read_only=True, data_only=True)
    try:
        sheets = {name: list(workbook[name].values) for name in ("DISCOVERY", "ENGAGEMENT", "FOLLOWERS", "TOP POSTS")}
        result = import_metrics(data, sheets, args.observed_at, args.reactions)
    finally:
        workbook.close()
    args.data.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    print(f"Updated one year; preserved {len(result['posts'])} selected posts across {len(result['years'])} years.")


if __name__ == "__main__":
    main()
