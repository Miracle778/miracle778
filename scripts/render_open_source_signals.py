#!/usr/bin/env python3
"""Render Open Source Activity data as dark and light static SVG timelines."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path("data/open-source-signals.yml")
GENERATED_PATH = Path("data/open-source-signals.generated.json")
DARK_SVG_PATH = Path("assets/open-source-signals-dark.svg")
LIGHT_SVG_PATH = Path("assets/open-source-signals-light.svg")

STATUS_WEIGHTS = {
    "merged": 100,
    "fixed": 90,
    "accepted": 80,
    "replied": 60,
    "open": 40,
    "closed": 20,
    "unknown": 10,
}

THEMES = {
    "dark": {
        "bg": "#020b18",
        "panel": "#061426",
        "card": "#07182b",
        "stats": "#081a2f",
        "date_bg": "#031d27",
        "line": "#00c7b4",
        "accent": "#19f5d0",
        "accent_soft": "#59f2d0",
        "text": "#f4f7ff",
        "muted": "#b8c3d8",
        "soft": "#29415f",
        "divider": "#2a3d58",
    },
    "light": {
        "bg": "#f4fbff",
        "panel": "#ffffff",
        "card": "#ffffff",
        "stats": "#f7fcff",
        "date_bg": "#e9fbf7",
        "line": "#13b8a6",
        "accent": "#059b8d",
        "accent_soft": "#39d6c2",
        "text": "#172133",
        "muted": "#53627a",
        "soft": "#c6d8ea",
        "divider": "#d4e2f0",
    },
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_generated(path: Path = GENERATED_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"activities": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"activities": payload}
    return payload


def truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"
    return text[: max_chars - 1] + "…"


def status_weight(status: str | None) -> int:
    return STATUS_WEIGHTS.get(status or "unknown", STATUS_WEIGHTS["unknown"])


def build_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(items),
        "types": Counter(item.get("type", "Unknown") for item in items),
        "statuses": Counter(item.get("status", "unknown") for item in items),
    }


def build_project_groups(
    activities: list[dict[str, Any]],
    featured_repos: list[str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for activity in activities:
        grouped[activity.get("repo") or "unknown/repo"].append(activity)

    featured_rank = {repo: index for index, repo in enumerate(featured_repos or [])}
    projects = []
    for repo, items in grouped.items():
        sorted_items = sorted(
            items,
            key=lambda item: (
                bool(item.get("featured")),
                status_weight(item.get("status")),
                item.get("updated_at") or item.get("created_at") or "",
            ),
            reverse=True,
        )
        projects.append({
            "repo": repo,
            "featured_rank": featured_rank.get(repo),
            "featured_repo": repo in featured_rank,
            "has_featured_item": any(item.get("featured") for item in items),
            "max_status_weight": max(status_weight(item.get("status")) for item in items),
            "timeline_date": activity_month(sorted_items[0]),
            "latest_updated_at": max(item.get("updated_at") or item.get("created_at") or "" for item in items),
            "repo_stars": first_repo_stars(items),
            "items": sorted_items,
            "stats": build_stats(items),
        })

    featured_projects = sorted(
        (project for project in projects if project["featured_rank"] is not None),
        key=lambda project: project["featured_rank"],
    )
    other_projects = sorted(
        (project for project in projects if project["featured_rank"] is None),
        key=lambda project: (
            project["has_featured_item"],
            project["max_status_weight"],
            project["latest_updated_at"],
        ),
        reverse=True,
    )
    return featured_projects + other_projects


def select_projects(
    projects: list[dict[str, Any]],
    max_projects: int,
    max_items_per_project: int,
) -> list[dict[str, Any]]:
    selected = []
    for project in projects[:max_projects]:
        copy = dict(project)
        copy["items"] = project["items"][:max_items_per_project]
        selected.append(copy)
    return selected


def title_case_status(status: str | None) -> str:
    return str(status or "unknown").replace("_", " ").title()


def activity_month(activity: dict[str, Any]) -> str:
    if activity.get("date"):
        return str(activity["date"])[:7]
    if activity.get("created_at"):
        return str(activity["created_at"])[:7]
    return str(activity.get("updated_at") or "")[:7]


def first_repo_stars(items: list[dict[str, Any]]) -> int | None:
    for item in items:
        if item.get("repo_stars") is not None:
            return item["repo_stars"]
    return None


def format_stars(count: int | None) -> str:
    if count is None:
        return ""
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


def project_title(project: dict[str, Any]) -> str:
    stars = format_stars(project.get("repo_stars"))
    if not stars:
        return project["repo"]
    return f"{project['repo']} · {stars}"


def stats_lines(stats: dict[str, Any]) -> list[str]:
    type_order = {"PR": 0, "Issue": 1}
    type_line = " · ".join(
        f"{key} {value}"
        for key, value in sorted(stats["types"].items(), key=lambda pair: type_order.get(pair[0], 99))
    )
    status_items = sorted(
        stats["statuses"].items(),
        key=lambda pair: (status_weight(pair[0]), pair[0]),
        reverse=True,
    )[:3]
    status_line = " · ".join(f"{title_case_status(key)} {value}" for key, value in status_items)
    return [
        f"Total {stats['total']}",
        truncate_text(type_line, 28),
        truncate_text(status_line, 32),
    ]


def svg_text(
    x: int,
    y: int,
    value: Any,
    size: int,
    fill: str,
    weight: str = "400",
    anchor: str = "start",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">'
        f"{html.escape(str(value))}</text>"
    )


def svg_line(x1: int, y1: int, x2: int, y2: int, color: str, width: int = 2) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'


def stats_icon(kind: str, x: int, y: int, color: str) -> str:
    if kind == "total":
        return "\n".join([
            f'<g class="stats-icon total" stroke="{color}" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
            svg_line(x, y + 12, x, y + 18, color),
            svg_line(x + 7, y + 7, x + 7, y + 18, color),
            svg_line(x + 14, y + 2, x + 14, y + 18, color),
            svg_line(x - 2, y + 20, x + 19, y + 20, color),
            f'<circle cx="{x}" cy="{y + 10}" r="2" fill="{color}" stroke="none"/>',
            f'<circle cx="{x + 7}" cy="{y + 5}" r="2" fill="{color}" stroke="none"/>',
            f'<circle cx="{x + 14}" cy="{y}" r="2" fill="{color}" stroke="none"/>',
            "</g>",
        ])
    if kind == "type":
        return "\n".join([
            f'<g class="stats-icon type" stroke="{color}" fill="none" stroke-width="2" stroke-linecap="round">',
            svg_line(x + 4, y + 4, x + 4, y + 18, color),
            svg_line(x + 4, y + 11, x + 15, y + 11, color),
            svg_line(x + 15, y + 11, x + 15, y + 18, color),
            f'<circle cx="{x + 4}" cy="{y + 4}" r="3" fill="none" stroke="{color}"/>',
            f'<circle cx="{x + 4}" cy="{y + 18}" r="3" fill="none" stroke="{color}"/>',
            f'<circle cx="{x + 15}" cy="{y + 18}" r="3" fill="none" stroke="{color}"/>',
            "</g>",
        ])
    return "\n".join([
        f'<g class="stats-icon status" stroke="{color}" fill="none" stroke-width="2" stroke-linecap="round">',
        f'<rect x="{x}" y="{y + 2}" width="20" height="15" rx="4"/>',
        svg_line(x + 5, y + 8, x + 15, y + 8, color),
        svg_line(x + 5, y + 12, x + 11, y + 12, color),
        f'<circle cx="{x + 5}" cy="{y + 21}" r="1.8" fill="{color}" stroke="none"/>',
        "</g>",
    ])


def render_empty_svg(title: str, colors: dict[str, str]) -> str:
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" viewBox="0 0 1200 260" role="img" aria-label="Open Source Activity">',
        f'<rect width="1200" height="260" rx="24" fill="{colors["bg"]}"/>',
        f'<rect x="28" y="24" width="1144" height="212" rx="22" fill="{colors["panel"]}" stroke="{colors["soft"]}"/>',
        svg_text(56, 76, title, 34, colors["text"], "700"),
        f'<line x1="56" y1="104" x2="1144" y2="104" stroke="{colors["divider"]}" stroke-width="1"/>',
        f'<rect x="56" y="128" width="1088" height="70" rx="14" fill="{colors["card"]}" stroke="{colors["soft"]}"/>',
        svg_text(600, 166, "No open source activity found yet.", 24, colors["muted"], "500", "middle"),
        "</svg>",
    ])


def render_svg(projects: list[dict[str, Any]], title: str, theme: str) -> str:
    colors = THEMES[theme]
    if not projects:
        return render_empty_svg(title, colors)

    row_height = 156
    height = 138 + row_height * len(projects) + 48
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-label="Open Source Activity">',
        f'<rect width="1200" height="{height}" rx="24" fill="{colors["bg"]}"/>',
        f'<rect x="28" y="24" width="1144" height="{height - 48}" rx="22" fill="{colors["panel"]}" stroke="{colors["soft"]}"/>',
        svg_text(56, 76, title, 34, colors["text"], "700"),
        f'<line x1="56" y1="104" x2="1144" y2="104" stroke="{colors["divider"]}" stroke-width="1"/>',
        f'<line x1="168" y1="132" x2="168" y2="{height - 74}" stroke="{colors["line"]}" stroke-width="3" opacity="0.78"/>',
    ]

    for index, project in enumerate(projects):
        y = 128 + index * row_height
        dot_y = y + 46
        latest_date = (project.get("timeline_date") or "")[:7]
        output.extend([
            f'<rect x="58" y="{dot_y - 20}" width="88" height="36" rx="7" fill="{colors["date_bg"]}" stroke="{colors["line"]}"/>',
            svg_text(102, dot_y + 5, latest_date, 18, colors["accent"], "600", "middle"),
            f'<circle cx="168" cy="{dot_y}" r="18" fill="{colors["accent"]}" opacity="0.12"/>',
            f'<circle cx="168" cy="{dot_y}" r="12" fill="{colors["accent_soft"]}" opacity="0.45"/>',
            f'<circle cx="168" cy="{dot_y}" r="8" fill="{colors["accent_soft"]}"/>',
            f'<rect x="196" y="{y}" width="648" height="126" rx="12" fill="{colors["card"]}" stroke="{colors["soft"]}"/>',
            f'<rect x="870" y="{y + 10}" width="274" height="106" rx="9" fill="{colors["stats"]}" stroke="{colors["soft"]}"/>',
            svg_text(216, y + 34, truncate_text(project_title(project), 52), 22, colors["text"], "700"),
        ])

        for item_index, item in enumerate(project["items"]):
            item_y = y + 64 + item_index * 25
            status = title_case_status(item.get("status"))
            label = f'{item.get("type", "Item")} · {status} · {truncate_text(item.get("title", ""), 66)}'
            output.append(f'<circle cx="218" cy="{item_y - 5}" r="2.5" fill="{colors["accent"]}"/>')
            output.append(svg_text(232, item_y, label, 16, colors["muted"]))

        stat_rows = stats_lines(project["stats"])
        output.extend([
            stats_icon("total", 892, y + 24, colors["accent"]),
            svg_text(924, y + 42, stat_rows[0], 17, colors["accent"], "600"),
            f'<line x1="894" y1="{y + 54}" x2="1126" y2="{y + 54}" stroke="{colors["divider"]}" stroke-width="1"/>',
            stats_icon("type", 892, y + 67, colors["accent"]),
            svg_text(924, y + 86, stat_rows[1], 16, colors["text"], "400"),
            stats_icon("status", 892, y + 93, colors["accent"]),
            svg_text(924, y + 112, stat_rows[2], 16, colors["text"], "400"),
        ])

    output.append("</svg>")
    return "\n".join(output)


def render_all() -> None:
    config = load_config()
    generated = load_generated()
    display = config.get("display", {})
    title = display.get("title") or "Open Source Activity"
    max_projects = int(display.get("max_projects") or 5)
    max_items_per_project = int(display.get("max_items_per_project") or 3)
    featured_repos = config.get("featured_repos") or []
    activities = generated.get("activities") or []

    projects = select_projects(
        build_project_groups(activities, featured_repos),
        max_projects=max_projects,
        max_items_per_project=max_items_per_project,
    )

    DARK_SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DARK_SVG_PATH.write_text(render_svg(projects, title, "dark") + "\n", encoding="utf-8")
    LIGHT_SVG_PATH.write_text(render_svg(projects, title, "light") + "\n", encoding="utf-8")
    print(f"Wrote {DARK_SVG_PATH} and {LIGHT_SVG_PATH}")


if __name__ == "__main__":
    render_all()
