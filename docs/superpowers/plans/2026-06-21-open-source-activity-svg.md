# Open Source Activity SVG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated GitHub Profile README module that fetches public GitHub PR/Issue activity and renders a dark/light static SVG timeline titled `Open Source Activity`.

**Architecture:** Add an independent Python pipeline beside the existing Node table updater. The fetch script reads YAML config and GitHub API data into `data/open-source-signals.generated.json`; the render script groups that JSON by repo and writes two static SVGs. README uses the SVG as the main section display while preserving the existing Markdown table inside a folded full log.

**Tech Stack:** Python 3, `requests`, `PyYAML`, built-in `unittest`, GitHub REST API, static SVG, GitHub Actions.

---

## File Map

- Create `data/open-source-signals.yml`: profile/display/filter/featured/override config.
- Create `data/open-source-signals.generated.json`: generated activity data, committed so README has stable SVG output.
- Create `scripts/fetch_github_activity.py`: GitHub API fetching, normalization, status inference, override application.
- Create `scripts/render_open_source_signals.py`: grouping, sorting, stats, SVG rendering.
- Create `tests/test_open_source_signals.py`: unit tests for inference, overrides, grouping, rendering constraints.
- Create `assets/open-source-signals-dark.svg`: generated dark SVG.
- Create `assets/open-source-signals-light.svg`: generated light SVG.
- Create or modify `requirements.txt`: include `PyYAML` and `requests`.
- Modify `README.md`: replace main table position with SVG `<picture>` and fold the existing table under `Full contribution log`.
- Create `.github/workflows/update-open-source-signals.yml`: scheduled/manual workflow to update JSON and SVG.

---

### Task 1: Add Config And Python Dependencies

**Files:**
- Create: `data/open-source-signals.yml`
- Create/Modify: `requirements.txt`

- [ ] **Step 1: Create the data directory**

Run:

```bash
mkdir -p data
```

Expected: command exits with status `0`.

- [ ] **Step 2: Create `data/open-source-signals.yml`**

Write this exact YAML:

```yaml
profile:
  username: "Miracle778"

display:
  title: "Open Source Activity"
  max_projects: 5
  max_items_per_project: 3
  lookback_days: null

filters:
  exclude_repos: []
  include_types:
    - "PR"
    - "Issue"

featured_repos:
  - "bytedance/deer-flow"
  - "microsoft/agent-governance-toolkit"
  - "NanmiCoder/MediaCrawler"
  - "bcgit/bc-java"

overrides:
  "https://github.com/bcgit/bc-java/issues/1355":
    status: "fixed"
    title: "SM2SignedData certificate parsing discussion"
    featured: true
```

- [ ] **Step 3: Create or update `requirements.txt`**

Ensure the file contains:

```text
PyYAML
requests
```

If `requirements.txt` already exists, add only missing lines and keep unrelated existing dependencies.

- [ ] **Step 4: Validate YAML loads**

Run:

```bash
python - <<'PY'
import yaml
from pathlib import Path
config = yaml.safe_load(Path("data/open-source-signals.yml").read_text())
assert config["profile"]["username"] == "Miracle778"
assert config["display"]["title"] == "Open Source Activity"
assert config["display"]["lookback_days"] is None
assert config["display"]["max_items_per_project"] == 3
print("config ok")
PY
```

Expected:

```text
config ok
```

- [ ] **Step 5: Commit**

Run:

```bash
git add data/open-source-signals.yml requirements.txt
git commit -m "Add open source activity config"
```

---

### Task 2: Add Fetch Script Core Logic With Unit Tests

**Files:**
- Create: `scripts/fetch_github_activity.py`
- Create: `tests/test_open_source_signals.py`

- [ ] **Step 1: Create the tests directory**

Run:

```bash
mkdir -p tests
```

Expected: command exits with status `0`.

- [ ] **Step 2: Write failing tests for fetch logic**

Create `tests/test_open_source_signals.py` with these tests first:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.fetch_github_activity import (
    STATUS_WEIGHTS,
    apply_overrides,
    build_search_query,
    infer_status,
    is_maintainer_comment,
    normalize_search_item,
)


class FetchGithubActivityTests(unittest.TestCase):
    def test_build_search_query_omits_created_filter_when_lookback_is_none(self):
        query = build_search_query("Miracle778", "PR", None)
        self.assertEqual(query, "author:Miracle778 type:pr")

    def test_build_search_query_adds_created_filter_when_lookback_is_number(self):
        query = build_search_query("Miracle778", "Issue", 30, today="2026-06-21")
        self.assertEqual(query, "author:Miracle778 type:issue created:>=2026-05-22")

    def test_maintainer_comment_requires_association_and_non_user(self):
        comment = {
            "user": {"login": "maintainer", "type": "User"},
            "author_association": "MEMBER",
            "body": "fixed in main",
        }
        self.assertTrue(is_maintainer_comment(comment, "Miracle778"))

    def test_maintainer_comment_excludes_user_and_bots(self):
        self.assertFalse(is_maintainer_comment({
            "user": {"login": "Miracle778", "type": "User"},
            "author_association": "MEMBER",
            "body": "self note",
        }, "Miracle778"))
        self.assertFalse(is_maintainer_comment({
            "user": {"login": "actions-bot", "type": "Bot"},
            "author_association": "MEMBER",
            "body": "done",
        }, "Miracle778"))

    def test_pr_status_prefers_merged(self):
        status = infer_status(
            activity_type="PR",
            state="closed",
            merged_at="2026-06-21T00:00:00Z",
            comments=[],
            timeline_events=[],
            username="Miracle778",
        )
        self.assertEqual(status, "merged")

    def test_issue_fixed_by_cross_referenced_pr(self):
        status = infer_status(
            activity_type="Issue",
            state="closed",
            merged_at=None,
            comments=[],
            timeline_events=[{
                "event": "cross-referenced",
                "source": {"issue": {"pull_request": {"url": "https://api.github.com/repos/o/r/pulls/1"}}},
            }],
            username="Miracle778",
        )
        self.assertEqual(status, "fixed")

    def test_issue_fixed_by_maintainer_keyword(self):
        status = infer_status(
            activity_type="Issue",
            state="closed",
            merged_at=None,
            comments=[{
                "user": {"login": "maintainer", "type": "User"},
                "author_association": "OWNER",
                "body": "已修复，感谢反馈",
            }],
            timeline_events=[],
            username="Miracle778",
        )
        self.assertEqual(status, "fixed")

    def test_replied_does_not_override_merged(self):
        status = infer_status(
            activity_type="PR",
            state="closed",
            merged_at="2026-06-21T00:00:00Z",
            comments=[{
                "user": {"login": "maintainer", "type": "User"},
                "author_association": "MEMBER",
                "body": "looks good",
            }],
            timeline_events=[],
            username="Miracle778",
        )
        self.assertEqual(status, "merged")
        self.assertGreater(STATUS_WEIGHTS["merged"], STATUS_WEIGHTS["replied"])

    def test_apply_overrides_has_highest_priority(self):
        activity = {
            "url": "https://github.com/o/r/issues/1",
            "title": "Original title",
            "status": "open",
            "featured": False,
        }
        result = apply_overrides(activity, {
            "https://github.com/o/r/issues/1": {
                "title": "Manual title",
                "status": "fixed",
                "featured": True,
            }
        })
        self.assertEqual(result["title"], "Manual title")
        self.assertEqual(result["status"], "fixed")
        self.assertTrue(result["featured"])

    def test_normalize_search_item_extracts_repo_and_type(self):
        item = {
            "html_url": "https://github.com/o/r/pull/12",
            "repository_url": "https://api.github.com/repos/o/r",
            "title": "Fix parser",
            "number": 12,
            "state": "open",
            "created_at": "2026-06-01T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z",
            "closed_at": None,
            "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/12"},
        }
        normalized = normalize_search_item(item)
        self.assertEqual(normalized["repo"], "o/r")
        self.assertEqual(normalized["type"], "PR")
        self.assertEqual(normalized["date"], "2026-06")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
python -m unittest tests/test_open_source_signals.py
```

Expected: FAIL or ERROR because `scripts.fetch_github_activity` does not exist yet.

- [ ] **Step 4: Implement `scripts/fetch_github_activity.py`**

Create the script with these public functions and CLI behavior:

```python
#!/usr/bin/env python3
import json
import os
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import yaml


CONFIG_PATH = Path("data/open-source-signals.yml")
OUTPUT_PATH = Path("data/open-source-signals.generated.json")
API_ROOT = "https://api.github.com"

STATUS_WEIGHTS = {
    "merged": 100,
    "fixed": 90,
    "accepted": 80,
    "replied": 60,
    "open": 40,
    "closed": 20,
    "unknown": 10,
}

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
FIX_KEYWORDS = (
    "fixed", "fix", "resolved", "merged", "released", "addressed", "done",
    "已修复", "已合并", "已处理", "修复了",
)


def load_config(path=CONFIG_PATH):
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_search_query(username, activity_type, lookback_days, today=None):
    type_value = "pr" if activity_type == "PR" else "issue"
    parts = [f"author:{username}", f"type:{type_value}"]
    if lookback_days is not None:
        base = date.fromisoformat(today) if today else date.today()
        since = base - timedelta(days=int(lookback_days))
        parts.append(f"created:>={since.isoformat()}")
    return " ".join(parts)


def request_json(session, url, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = session.get(url, headers=headers, timeout=30)
    remaining = response.headers.get("X-RateLimit-Remaining")
    if response.status_code == 403 and remaining == "0":
        reset = response.headers.get("X-RateLimit-Reset", "unknown")
        raise RuntimeError(f"GitHub API rate limit exceeded; reset={reset}")
    if not response.ok:
        raise RuntimeError(f"GitHub API request failed: {response.status_code} {response.text[:500]}")
    return response.json()


def paginated_get(session, url, token, max_pages=10):
    results = []
    page_url = url
    pages = 0
    while page_url and pages < max_pages:
        data = request_json(session, page_url, token)
        if isinstance(data, dict) and "items" in data:
            results.extend(data["items"])
        elif isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        pages += 1
        page_url = None
    return results


def search_activities(session, username, activity_type, lookback_days, token):
    query = quote(build_search_query(username, activity_type, lookback_days))
    url = f"{API_ROOT}/search/issues?q={query}&sort=created&order=desc&per_page=100"
    payload = request_json(session, url, token)
    return payload.get("items", [])


def repo_from_repository_url(repository_url):
    return repository_url.removeprefix(f"{API_ROOT}/repos/")


def normalize_search_item(item):
    activity_type = "PR" if "pull_request" in item else "Issue"
    created_at = item.get("created_at") or ""
    return {
        "date": created_at[:7] if len(created_at) >= 7 else "",
        "repo": repo_from_repository_url(item.get("repository_url", "")),
        "type": activity_type,
        "title": item.get("title") or "",
        "status": "unknown",
        "url": item.get("html_url") or "",
        "number": item.get("number"),
        "created_at": created_at,
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "merged_at": None,
        "featured": False,
    }


def is_maintainer_comment(comment, username):
    user = comment.get("user") or {}
    login = user.get("login")
    if not login or login.lower() == username.lower():
        return False
    if user.get("type") == "Bot" or login.endswith("[bot]"):
        return False
    return comment.get("author_association") in MAINTAINER_ASSOCIATIONS


def has_fix_keyword(comment):
    body = (comment.get("body") or "").lower()
    return any(keyword.lower() in body for keyword in FIX_KEYWORDS)


def has_cross_referenced_pr(timeline_events):
    for event in timeline_events:
        if event.get("event") != "cross-referenced":
            continue
        source_issue = ((event.get("source") or {}).get("issue") or {})
        if source_issue.get("pull_request"):
            return True
    return False


def stronger_status(current, candidate):
    if STATUS_WEIGHTS.get(candidate, 0) > STATUS_WEIGHTS.get(current, 0):
        return candidate
    return current


def infer_status(activity_type, state, merged_at, comments, timeline_events, username):
    state_value = (state or "").lower()
    if activity_type == "PR":
        status = "merged" if merged_at else ("open" if state_value == "open" else "closed")
    elif activity_type == "Issue":
        status = "open" if state_value == "open" else ("closed" if state_value == "closed" else "unknown")
    else:
        status = "unknown"

    maintainer_comments = [comment for comment in comments if is_maintainer_comment(comment, username)]

    if activity_type == "Issue" and status == "closed":
        if has_cross_referenced_pr(timeline_events) or any(has_fix_keyword(comment) for comment in maintainer_comments):
            status = stronger_status(status, "fixed")

    if maintainer_comments:
        status = stronger_status(status, "replied")

    return status


def apply_overrides(activity, overrides):
    result = deepcopy(activity)
    override = (overrides or {}).get(result.get("url")) or {}
    for key in ("status", "title", "featured"):
        if key in override:
            result[key] = override[key]
    return result


def should_skip_self_fixed_issue(activity, username):
    return activity.get("type") == "Issue" and activity.get("self_fixed") is True


def fetch_activity_details(session, item, token, username):
    activity = normalize_search_item(item)
    comments_url = item.get("comments_url")
    comments = paginated_get(session, comments_url, token, max_pages=3) if comments_url else []
    timeline_events = []
    merged_at = None
    self_fixed = False

    if activity["type"] == "PR":
        pr_url = item.get("pull_request", {}).get("url")
        if pr_url:
            pr_payload = request_json(session, pr_url, token)
            merged_at = pr_payload.get("merged_at")
    else:
        timeline_url = f"{API_ROOT}/repos/{activity['repo']}/issues/{activity['number']}/timeline"
        timeline_events = paginated_get(session, timeline_url, token, max_pages=3)
        for event in timeline_events:
            source_issue = ((event.get("source") or {}).get("issue") or {})
            source_pr = source_issue.get("pull_request")
            source_user = (source_issue.get("user") or {}).get("login")
            if event.get("event") == "cross-referenced" and source_pr and source_user and source_user.lower() == username.lower():
                self_fixed = True

    activity["merged_at"] = merged_at
    activity["status"] = infer_status(activity["type"], item.get("state"), merged_at, comments, timeline_events, username)
    activity["self_fixed"] = self_fixed
    return activity


def collect_activities(config, token):
    username = config.get("profile", {}).get("username") or "Miracle778"
    display = config.get("display", {})
    filters = config.get("filters", {})
    lookback_days = display.get("lookback_days")
    include_types = filters.get("include_types") or ["PR", "Issue"]
    exclude_repos = set(filters.get("exclude_repos") or [])
    overrides = config.get("overrides") or {}

    session = requests.Session()
    activities = []
    for activity_type in include_types:
        for item in search_activities(session, username, activity_type, lookback_days, token):
            activity = fetch_activity_details(session, item, token, username)
            if activity["repo"] in exclude_repos:
                continue
            activity = apply_overrides(activity, overrides)
            if should_skip_self_fixed_issue(activity, username):
                continue
            activities.append(activity)

    activities.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "username": username,
        "activities": activities,
    }


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Missing GITHUB_TOKEN; set it before running fetch_github_activity.py", file=sys.stderr)
        return 1
    config = load_config()
    payload = collect_activities(config, token)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(payload['activities'])} activities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
python -m unittest tests/test_open_source_signals.py
```

Expected:

```text
Ran 10 tests

OK
```

- [ ] **Step 6: Commit**

Run:

```bash
git add scripts/fetch_github_activity.py tests/test_open_source_signals.py
git commit -m "Add GitHub activity fetch logic"
```

---

### Task 3: Add Render Script With Grouping And SVG Tests

**Files:**
- Create: `scripts/render_open_source_signals.py`
- Modify: `tests/test_open_source_signals.py`

- [ ] **Step 1: Add rendering tests**

Append these imports to `tests/test_open_source_signals.py`:

```python
from scripts.render_open_source_signals import (
    build_project_groups,
    render_svg,
    select_projects,
    truncate_text,
)
```

Append these tests before the `if __name__ == "__main__":` block:

```python
class RenderOpenSourceSignalsTests(unittest.TestCase):
    def test_truncate_text_adds_ellipsis(self):
        self.assertEqual(truncate_text("abcdef", 4), "abc…")
        self.assertEqual(truncate_text("abc", 4), "abc")

    def test_build_project_groups_groups_by_repo_and_counts_all_items(self):
        activities = [
            {"repo": "o/r", "type": "PR", "status": "merged", "title": "A", "updated_at": "2026-06-03T00:00:00Z", "featured": False},
            {"repo": "o/r", "type": "Issue", "status": "replied", "title": "B", "updated_at": "2026-06-02T00:00:00Z", "featured": False},
            {"repo": "x/y", "type": "Issue", "status": "open", "title": "C", "updated_at": "2026-06-01T00:00:00Z", "featured": False},
        ]
        groups = build_project_groups(activities, featured_repos=[])
        self.assertEqual(groups[0]["repo"], "o/r")
        self.assertEqual(groups[0]["stats"]["total"], 2)
        self.assertEqual(groups[0]["stats"]["types"]["PR"], 1)
        self.assertEqual(groups[0]["stats"]["types"]["Issue"], 1)

    def test_select_projects_limits_projects_and_items(self):
        activities = []
        for index in range(6):
            for item_index in range(4):
                activities.append({
                    "repo": f"o/r{index}",
                    "type": "PR",
                    "status": "open",
                    "title": f"Item {item_index}",
                    "url": f"https://github.com/o/r{index}/pull/{item_index}",
                    "updated_at": f"2026-06-{10 - index:02d}T00:00:00Z",
                    "date": "2026-06",
                    "featured": False,
                })
        groups = build_project_groups(activities, featured_repos=[])
        selected = select_projects(groups, max_projects=5, max_items_per_project=3)
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(len(group["items"]) == 3 for group in selected))

    def test_featured_repo_is_sort_boost_not_filter(self):
        activities = [
            {"repo": "new/repo", "type": "PR", "status": "merged", "title": "New", "url": "https://github.com/new/repo/pull/1", "updated_at": "2026-06-21T00:00:00Z", "date": "2026-06", "featured": False},
            {"repo": "featured/repo", "type": "Issue", "status": "open", "title": "Old", "url": "https://github.com/featured/repo/issues/1", "updated_at": "2025-01-01T00:00:00Z", "date": "2025-01", "featured": False},
        ]
        groups = build_project_groups(activities, featured_repos=["featured/repo"])
        repos = [group["repo"] for group in select_projects(groups, max_projects=5, max_items_per_project=3)]
        self.assertIn("new/repo", repos)
        self.assertEqual(repos[0], "featured/repo")

    def test_render_svg_has_title_and_no_forbidden_elements(self):
        svg = render_svg([], title="Open Source Activity", theme="dark")
        self.assertIn("Open Source Activity", svg)
        self.assertIn("No open source activity found yet.", svg)
        self.assertNotIn("<script", svg)
        self.assertNotIn("foreignObject", svg)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m unittest tests/test_open_source_signals.py
```

Expected: FAIL or ERROR because `scripts.render_open_source_signals` does not exist yet.

- [ ] **Step 3: Implement `scripts/render_open_source_signals.py`**

Create the script:

```python
#!/usr/bin/env python3
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

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


def load_config(path=CONFIG_PATH):
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_generated(path=GENERATED_PATH):
    if not path.exists():
        return {"activities": []}
    return json.loads(path.read_text(encoding="utf-8"))


def truncate_text(value, max_chars):
    value = str(value or "")
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return "…"
    return value[: max_chars - 1] + "…"


def status_weight(status):
    return STATUS_WEIGHTS.get(status or "unknown", STATUS_WEIGHTS["unknown"])


def build_stats(items):
    return {
        "total": len(items),
        "types": Counter(item.get("type", "Unknown") for item in items),
        "statuses": Counter(item.get("status", "unknown") for item in items),
    }


def build_project_groups(activities, featured_repos):
    grouped = defaultdict(list)
    for activity in activities:
        repo = activity.get("repo") or "unknown/repo"
        grouped[repo].append(activity)

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


def select_projects(projects, max_projects, max_items_per_project):
    selected = []
    for project in projects[:max_projects]:
        copy = dict(project)
        copy["items"] = project["items"][:max_items_per_project]
        selected.append(copy)
    return selected


def title_case_status(status):
    return str(status or "unknown").replace("_", " ").title()


def stats_lines(stats):
    type_line = " · ".join(f"{key} {value}" for key, value in sorted(stats["types"].items()))
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


def text(x, y, value, size, fill, weight="400", anchor="start"):
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(str(value))}</text>'
    )


def render_empty_svg(title, colors):
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" viewBox="0 0 1200 260" role="img" aria-label="Open Source Activity">',
        f'<rect width="1200" height="260" rx="24" fill="{colors["bg"]}"/>',
        text(56, 72, title, 34, colors["text"], "700"),
        f'<rect x="56" y="112" width="1088" height="92" rx="18" fill="{colors["card"]}" stroke="{colors["soft"]}"/>',
        text(600, 166, "No open source activity found yet.", 24, colors["muted"], "500", "middle"),
        '</svg>',
    ])


def render_svg(projects, title, theme):
    colors = THEMES[theme]
    if not projects:
        return render_empty_svg(title, colors)

    row_height = 156
    height = 116 + row_height * len(projects) + 34
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-label="Open Source Activity">',
        f'<rect width="1200" height="{height}" rx="24" fill="{colors["bg"]}"/>',
        text(56, 72, title, 34, colors["text"], "700"),
        f'<line x1="154" y1="120" x2="154" y2="{height - 56}" stroke="{colors["line"]}" stroke-width="2"/>',
    ]

    for index, project in enumerate(projects):
        y = 116 + index * row_height
        dot_y = y + 46
        latest_date = (project.get("latest_updated_at") or "")[:7]
        output.extend([
            text(56, dot_y + 6, latest_date, 18, colors["muted"], "600"),
            f'<circle cx="154" cy="{dot_y}" r="9" fill="{colors["accent"]}"/>',
            f'<rect x="188" y="{y}" width="676" height="126" rx="18" fill="{colors["card"]}" stroke="{colors["soft"]}"/>',
            f'<rect x="890" y="{y}" width="254" height="126" rx="18" fill="{colors["stats"]}" stroke="{colors["soft"]}"/>',
            text(214, y + 34, truncate_text(project["repo"], 42), 22, colors["text"], "700"),
        ])

        for item_index, item in enumerate(project["items"]):
            item_y = y + 64 + item_index * 25
            status = title_case_status(item.get("status"))
            label = f'{item.get("type", "Item")} · {status} · {truncate_text(item.get("title", ""), 70)}'
            output.append(text(214, item_y, label, 16, colors["muted"], "400"))

        for line_index, line in enumerate(stats_lines(project["stats"])):
            output.append(text(918, y + 38 + line_index * 27, line, 17, colors["text"] if line_index == 0 else colors["muted"], "600" if line_index == 0 else "400"))

    output.append("</svg>")
    return "\n".join(output)


def render_all():
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
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
python -m unittest tests/test_open_source_signals.py
```

Expected:

```text
Ran 15 tests

OK
```

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/render_open_source_signals.py tests/test_open_source_signals.py
git commit -m "Add open source activity SVG renderer"
```

---

### Task 4: Generate Initial JSON And SVG Assets

**Files:**
- Create: `data/open-source-signals.generated.json`
- Create: `assets/open-source-signals-dark.svg`
- Create: `assets/open-source-signals-light.svg`

- [ ] **Step 1: Install Python dependencies**

Run:

```bash
python -m pip install -r requirements.txt
```

Expected: command exits with status `0`.

- [ ] **Step 2: Generate activity JSON with GitHub data**

Run:

```bash
GITHUB_TOKEN="$(gh auth token)" python scripts/fetch_github_activity.py
```

Expected:

```text
Wrote data/open-source-signals.generated.json with N activities
```

where `N` is `0` or greater.

If `gh auth token` is unavailable, run with an exported token:

```bash
GITHUB_TOKEN="$GITHUB_TOKEN" python scripts/fetch_github_activity.py
```

- [ ] **Step 3: Generate SVG files**

Run:

```bash
python scripts/render_open_source_signals.py
```

Expected:

```text
Wrote assets/open-source-signals-dark.svg and assets/open-source-signals-light.svg
```

- [ ] **Step 4: Verify generated files exist and contain expected text**

Run:

```bash
python - <<'PY'
from pathlib import Path
for path in [
    Path("data/open-source-signals.generated.json"),
    Path("assets/open-source-signals-dark.svg"),
    Path("assets/open-source-signals-light.svg"),
]:
    assert path.exists(), path
dark = Path("assets/open-source-signals-dark.svg").read_text(encoding="utf-8")
light = Path("assets/open-source-signals-light.svg").read_text(encoding="utf-8")
for svg in (dark, light):
    assert "Open Source Activity" in svg
    assert "<script" not in svg
    assert "foreignObject" not in svg
print("generated assets ok")
PY
```

Expected:

```text
generated assets ok
```

- [ ] **Step 5: Commit**

Run:

```bash
git add data/open-source-signals.generated.json assets/open-source-signals-dark.svg assets/open-source-signals-light.svg
git commit -m "Generate initial open source activity SVGs"
```

---

### Task 5: Integrate SVG Into README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Open Source Activity section**

Replace the current section shape:

```md
## Open Source Activity

<!-- CONTRIBUTIONS:START -->
...
<!-- CONTRIBUTIONS:END -->
```

with this shape, preserving the exact existing generated table between the contribution markers:

```md
## Open Source Activity

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/open-source-signals-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="./assets/open-source-signals-light.svg">
  <img src="./assets/open-source-signals-dark.svg" width="100%" alt="Open Source Activity">
</picture>

<details>
<summary>Full contribution log</summary>

<!-- CONTRIBUTIONS:START -->
| Date | Repository | Stars | Type | Record | Discuss | Status | Signal |
|---|---|---:|---|---|---:|---|---|
existing generated rows stay here

[View all PRs](https://github.com/pulls?q=author%3AMiracle778) · [View all Issues](https://github.com/issues?q=author%3AMiracle778)
<!-- CONTRIBUTIONS:END -->

</details>
```

Do not delete or edit the generated table rows unless needed to move them inside the details block.

- [ ] **Step 2: Verify README has one main section and folded log**

Run:

```bash
python - <<'PY'
from pathlib import Path
readme = Path("README.md").read_text(encoding="utf-8")
assert readme.count("## Open Source Activity") == 1
assert "./assets/open-source-signals-dark.svg" in readme
assert "./assets/open-source-signals-light.svg" in readme
assert "<details>" in readme
assert "<summary>Full contribution log</summary>" in readme
assert "<!-- CONTRIBUTIONS:START -->" in readme
assert "<!-- CONTRIBUTIONS:END -->" in readme
print("README integration ok")
PY
```

Expected:

```text
README integration ok
```

- [ ] **Step 3: Commit**

Run:

```bash
git add README.md
git commit -m "Show open source activity SVG in README"
```

---

### Task 6: Add GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/update-open-source-signals.yml`

- [ ] **Step 1: Create workflow file**

Write `.github/workflows/update-open-source-signals.yml`:

```yaml
name: Update Open Source Activity SVG

on:
  workflow_dispatch:
  schedule:
    - cron: "17 16 * * *"

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Fetch GitHub activity
        run: python scripts/fetch_github_activity.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Render SVG
        run: python scripts/render_open_source_signals.py

      - name: Commit changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/open-source-signals.generated.json assets/open-source-signals-dark.svg assets/open-source-signals-light.svg README.md
          if git diff --cached --quiet; then
            echo "No open source activity changes to commit"
            exit 0
          fi
          git commit -m "Update open source activity SVG"
          git pull --rebase origin main
          git push
```

- [ ] **Step 2: Validate workflow YAML parses**

Run:

```bash
python - <<'PY'
from pathlib import Path
import yaml
workflow = yaml.safe_load(Path(".github/workflows/update-open-source-signals.yml").read_text())
assert workflow["name"] == "Update Open Source Activity SVG"
assert "workflow_dispatch" in workflow[True]
assert workflow["permissions"]["contents"] == "write"
print("workflow ok")
PY
```

Expected:

```text
workflow ok
```

Note: PyYAML may parse the key `on` as boolean `True`, so the assertion intentionally uses `workflow[True]`.

- [ ] **Step 3: Commit**

Run:

```bash
git add .github/workflows/update-open-source-signals.yml
git commit -m "Add open source activity SVG workflow"
```

---

### Task 7: Final Verification And Push

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run Python unit tests**

Run:

```bash
python -m unittest tests/test_open_source_signals.py
```

Expected:

```text
OK
```

- [ ] **Step 2: Run existing Node tests**

Run:

```bash
node --check scripts/update-contributions.mjs
node --test scripts/update-contributions.test.mjs
```

Expected: syntax check exits `0`, Node tests report all pass.

- [ ] **Step 3: Re-render SVG**

Run:

```bash
python scripts/render_open_source_signals.py
```

Expected:

```text
Wrote assets/open-source-signals-dark.svg and assets/open-source-signals-light.svg
```

- [ ] **Step 4: Run acceptance check**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

generated = json.loads(Path("data/open-source-signals.generated.json").read_text(encoding="utf-8"))
assert "activities" in generated
for path in ["assets/open-source-signals-dark.svg", "assets/open-source-signals-light.svg"]:
    svg = Path(path).read_text(encoding="utf-8")
    assert "Open Source Activity" in svg
    assert "Open Source Signals" not in svg
    assert "<script" not in svg
    assert "foreignObject" not in svg
    assert "tag" not in svg.lower()
readme = Path("README.md").read_text(encoding="utf-8")
assert "<picture>" in readme
assert "<details>" in readme
assert "<summary>Full contribution log</summary>" in readme
assert "<!-- CONTRIBUTIONS:START -->" in readme
assert "<!-- CONTRIBUTIONS:END -->" in readme
print("acceptance ok")
PY
```

Expected:

```text
acceptance ok
```

- [ ] **Step 5: Check git status**

Run:

```bash
git status --short --branch
```

Expected: only intentional files are modified or branch is clean. `.idea/` may remain untracked and must not be committed.

- [ ] **Step 6: Push**

Run:

```bash
git push
```

Expected: local commits are pushed to `origin/main`.
