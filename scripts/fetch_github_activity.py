#!/usr/bin/env python3
"""Fetch GitHub PR and Issue activity for the Open Source Activity SVG."""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml


CONFIG_PATH = Path("data/open-source-signals.yml")
OUTPUT_PATH = Path("data/open-source-signals.generated.json")
GITHUB_API = "https://api.github.com"
SEARCH_RESULTS_MAX_PAGES = 10

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
FIX_KEYWORDS = (
    "fixed",
    "fix",
    "fixes",
    "resolved",
    "done",
    "landed",
    "merged",
    "released",
    "addressed",
    "修复",
    "已修复",
    "已合并",
    "已处理",
    "修复了",
    "解决",
)
ACCEPTED_KEYWORDS = (
    "accepted",
    "approved",
    "will fix",
    "planned",
    "looks good",
    "lgtm",
)

STATUS_WEIGHTS = {
    "merged": 100,
    "fixed": 90,
    "accepted": 80,
    "replied": 60,
    "open": 40,
    "closed": 20,
    "unknown": 10,
}


def build_search_query(
    username: str,
    activity_type: str,
    lookback_days: int | None,
    *,
    today: str | date | None = None,
) -> str:
    github_type = "pr" if activity_type.lower() == "pr" else "issue"
    query = f"author:{username} type:{github_type}"
    if lookback_days is None:
        return query

    current_date = _coerce_date(today) if today is not None else date.today()
    since = current_date - timedelta(days=lookback_days)
    return f"{query} created:>={since.isoformat()}"


def is_maintainer_comment(comment: dict[str, Any], username: str) -> bool:
    user = comment.get("user") or {}
    login = user.get("login") or ""
    user_type = user.get("type") or ""
    association = comment.get("author_association") or ""

    if login.lower() == username.lower():
        return False
    if user_type.lower() == "bot":
        return False
    return association.upper() in MAINTAINER_ASSOCIATIONS


def infer_status(
    *,
    activity_type: str,
    state: str | None,
    merged_at: str | None,
    comments: list[dict[str, Any]],
    timeline_events: list[dict[str, Any]],
    username: str,
) -> str:
    candidates = ["unknown"]

    if (state or "").lower() == "open":
        candidates.append("open")
    elif (state or "").lower() == "closed":
        candidates.append("closed")

    if activity_type == "PR" and merged_at:
        candidates.append("merged")

    maintainer_comments = [
        comment for comment in comments if is_maintainer_comment(comment, username)
    ]
    if maintainer_comments:
        candidates.append("replied")

    if any(_contains_keyword(comment.get("body") or "", ACCEPTED_KEYWORDS) for comment in maintainer_comments):
        candidates.append("accepted")

    if activity_type == "Issue" and (state or "").lower() == "closed":
        if _has_cross_referenced_pr(timeline_events):
            candidates.append("fixed")
        if any(_contains_keyword(comment.get("body") or "", FIX_KEYWORDS) for comment in maintainer_comments):
            candidates.append("fixed")

    return max(candidates, key=lambda status: STATUS_WEIGHTS.get(status, 0))


def apply_overrides(
    activity: dict[str, Any],
    overrides: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    result = deepcopy(activity)
    if not overrides:
        return result

    override = overrides.get(result.get("url")) or overrides.get(result.get("html_url"))
    if not override:
        return result

    for key in ("status", "title", "featured"):
        if key in override:
            result[key] = override[key]
    return result


def normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_from_api_url(item.get("repository_url") or "")
    activity_type = "PR" if item.get("pull_request") else "Issue"
    created_at = item.get("created_at")

    return {
        "date": _month_from_timestamp(created_at),
        "repo": repo,
        "type": activity_type,
        "title": item.get("title") or "",
        "state": item.get("state"),
        "status": "unknown",
        "url": item.get("html_url") or "",
        "number": item.get("number"),
        "created_at": created_at,
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "merged_at": None,
        "featured": False,
    }


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-home-page-open-source-activity",
        })

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(url, params=params, timeout=30)
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset", "unknown")
            raise RuntimeError(f"GitHub API rate limit exceeded; reset={reset}")
        if response.status_code >= 400:
            raise RuntimeError(
                f"GitHub API request failed: {response.status_code} {response.text}"
            )
        return response.json()

    def get_all_pages(self, url: str, params: dict[str, Any] | None = None) -> list[Any]:
        items: list[Any] = []
        page = 1
        max_pages = SEARCH_RESULTS_MAX_PAGES if _is_search_issues_url(url) else None
        while True:
            page_params = dict(params or {})
            page_params.update({"page": page, "per_page": 100})
            payload = self.get(url, page_params)
            if isinstance(payload, dict) and "items" in payload:
                page_items = payload["items"]
            elif isinstance(payload, list):
                page_items = payload
            else:
                raise RuntimeError(f"Unexpected GitHub API response shape for {url}")

            items.extend(page_items)
            if len(page_items) < 100:
                return items
            if max_pages is not None and page >= max_pages:
                return items
            page += 1


def fetch_activity(config: dict[str, Any], client: GitHubClient) -> list[dict[str, Any]]:
    username = config["profile"]["username"]
    lookback_days = config.get("display", {}).get("lookback_days")
    include_types = config.get("filters", {}).get("include_types", ["PR", "Issue"])
    exclude_repos = set(config.get("filters", {}).get("exclude_repos", []))
    featured_repos = set(config.get("featured_repos", []))
    overrides = config.get("overrides", {})

    activities: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for activity_type in include_types:
        query = build_search_query(username, activity_type, lookback_days)
        items = client.get_all_pages(
            f"{GITHUB_API}/search/issues",
            {"q": query, "sort": "updated", "order": "desc"},
        )
        for item in items:
            activity = normalize_search_item(item)
            if activity["repo"] in exclude_repos or activity["url"] in seen_urls:
                continue

            comments = _fetch_comments(client, item)
            timeline_events = _fetch_timeline(client, item)
            merged_at = _fetch_merged_at(client, item)

            if _is_self_fixed_issue(activity, timeline_events, username):
                continue

            activity["merged_at"] = merged_at
            activity["featured"] = activity["repo"] in featured_repos
            activity["status"] = infer_status(
                activity_type=activity["type"],
                state=item.get("state"),
                merged_at=merged_at,
                comments=comments,
                timeline_events=timeline_events,
                username=username,
            )
            activities.append(apply_overrides(activity, overrides))
            seen_urls.add(activity["url"])

    return sorted(
        activities,
        key=lambda activity: (
            bool(activity.get("featured")),
            activity.get("updated_at") or activity.get("created_at") or "",
        ),
        reverse=True,
    )


def build_generated_payload(
    *,
    username: str,
    activities: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = generated_at or (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    return {
        "generated_at": timestamp,
        "username": username,
        "activities": activities,
    }


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required to fetch GitHub activity.", file=sys.stderr)
        return 1

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    client = GitHubClient(token)
    activities = fetch_activity(config, client)
    payload = build_generated_payload(
        username=config["profile"]["username"],
        activities=activities,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(activities)} activities to {OUTPUT_PATH}")
    return 0


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _repo_from_api_url(repository_url: str) -> str:
    marker = "/repos/"
    if marker not in repository_url:
        return ""
    return repository_url.split(marker, 1)[1]


def _is_search_issues_url(url: str) -> bool:
    return url.rstrip("/") == f"{GITHUB_API}/search/issues" or "/search/issues" in url


def _month_from_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    return timestamp[:7]


def _contains_keyword(body: str, keywords: tuple[str, ...]) -> bool:
    lowered = body.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _has_cross_referenced_pr(timeline_events: list[dict[str, Any]]) -> bool:
    for event in timeline_events:
        if event.get("event") != "cross-referenced":
            continue
        source_issue = (event.get("source") or {}).get("issue") or {}
        if source_issue.get("pull_request"):
            return True
    return False


def _fetch_comments(client: GitHubClient, item: dict[str, Any]) -> list[dict[str, Any]]:
    comments_url = item.get("comments_url")
    if not comments_url:
        return []
    return client.get_all_pages(comments_url)


def _fetch_timeline(client: GitHubClient, item: dict[str, Any]) -> list[dict[str, Any]]:
    timeline_url = item.get("timeline_url")
    if not timeline_url:
        repo = _repo_from_api_url(item.get("repository_url") or "")
        number = item.get("number")
        if not repo or number is None:
            return []
        timeline_url = f"{GITHUB_API}/repos/{repo}/issues/{number}/timeline"
    return client.get_all_pages(timeline_url)


def _fetch_merged_at(client: GitHubClient, item: dict[str, Any]) -> str | None:
    pull_request = item.get("pull_request") or {}
    pr_url = pull_request.get("url")
    if not pr_url:
        return None
    return client.get(pr_url).get("merged_at")


def _is_self_fixed_issue(
    activity: dict[str, Any],
    timeline_events: list[dict[str, Any]],
    username: str,
) -> bool:
    if activity.get("type") != "Issue":
        return False
    if (activity.get("state") or "").lower() != "closed":
        return False

    for event in timeline_events:
        if event.get("event") != "cross-referenced":
            continue
        source_issue = (event.get("source") or {}).get("issue") or {}
        if not source_issue.get("pull_request"):
            continue
        source_user = (source_issue.get("user") or {}).get("login") or ""
        if source_user.lower() == username.lower() and _is_closed_or_merged_pr(source_issue):
            return True
    return False


def _is_closed_or_merged_pr(source_issue: dict[str, Any]) -> bool:
    pull_request = source_issue.get("pull_request") or {}

    if "merged" in pull_request:
        return bool(pull_request["merged"])
    if "merged_at" in pull_request:
        return bool(pull_request["merged_at"])
    return bool(source_issue.get("merged_at"))


if __name__ == "__main__":
    raise SystemExit(main())
