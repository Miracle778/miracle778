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
        "bg": "#071512",
        "card": "#0d211d",
        "stats": "#102a25",
        "line": "#1d6f63",
        "accent": "#2dd4bf",
        "text": "#e8fff9",
        "muted": "#8db7ae",
        "soft": "#163832",
    },
    "light": {
        "bg": "#f6fffc",
        "card": "#ffffff",
        "stats": "#ecfdf8",
        "line": "#7dd3c7",
        "accent": "#0f9f8f",
        "text": "#16312d",
        "muted": "#54716b",
        "soft": "#d8f3ee",
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

    featured_set = set(featured_repos or [])
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
            "featured_repo": repo in featured_set,
            "has_featured_item": any(item.get("featured") for item in items),
            "max_status_weight": max(status_weight(item.get("status")) for item in items),
            "timeline_date": activity_month(sorted_items[0]),
            "latest_updated_at": max(item.get("updated_at") or item.get("created_at") or "" for item in items),
            "items": sorted_items,
            "stats": build_stats(items),
        })

    return sorted(
        projects,
        key=lambda project: (
            project["featured_repo"],
            project["has_featured_item"],
            project["max_status_weight"],
            project["latest_updated_at"],
        ),
        reverse=True,
    )


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


def render_empty_svg(title: str, colors: dict[str, str]) -> str:
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" viewBox="0 0 1200 260" role="img" aria-label="Open Source Activity">',
        f'<rect width="1200" height="260" rx="24" fill="{colors["bg"]}"/>',
        svg_text(56, 72, title, 34, colors["text"], "700"),
        f'<rect x="56" y="112" width="1088" height="92" rx="18" fill="{colors["card"]}" stroke="{colors["soft"]}"/>',
        svg_text(600, 166, "No open source activity found yet.", 24, colors["muted"], "500", "middle"),
        "</svg>",
    ])


def render_svg(projects: list[dict[str, Any]], title: str, theme: str) -> str:
    colors = THEMES[theme]
    if not projects:
        return render_empty_svg(title, colors)

    row_height = 156
    height = 116 + row_height * len(projects) + 34
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-label="Open Source Activity">',
        f'<rect width="1200" height="{height}" rx="24" fill="{colors["bg"]}"/>',
        svg_text(56, 72, title, 34, colors["text"], "700"),
        f'<line x1="154" y1="120" x2="154" y2="{height - 56}" stroke="{colors["line"]}" stroke-width="2"/>',
    ]

    for index, project in enumerate(projects):
        y = 116 + index * row_height
        dot_y = y + 46
        latest_date = (project.get("timeline_date") or "")[:7]
        output.extend([
            svg_text(56, dot_y + 6, latest_date, 18, colors["muted"], "600"),
            f'<circle cx="154" cy="{dot_y}" r="9" fill="{colors["accent"]}"/>',
            f'<rect x="188" y="{y}" width="676" height="126" rx="18" fill="{colors["card"]}" stroke="{colors["soft"]}"/>',
            f'<rect x="890" y="{y}" width="254" height="126" rx="18" fill="{colors["stats"]}" stroke="{colors["soft"]}"/>',
            svg_text(214, y + 34, truncate_text(project["repo"], 42), 22, colors["text"], "700"),
        ])

        for item_index, item in enumerate(project["items"]):
            item_y = y + 64 + item_index * 25
            status = title_case_status(item.get("status"))
            label = f'{item.get("type", "Item")} · {status} · {truncate_text(item.get("title", ""), 70)}'
            output.append(svg_text(214, item_y, label, 16, colors["muted"]))

        for line_index, line in enumerate(stats_lines(project["stats"])):
            output.append(svg_text(
                918,
                y + 38 + line_index * 27,
                line,
                17,
                colors["text"] if line_index == 0 else colors["muted"],
                "600" if line_index == 0 else "400",
            ))

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
