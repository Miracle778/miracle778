import tempfile
import unittest
from pathlib import Path

from scripts.fetch_github_activity import (
    FIX_KEYWORDS,
    GITHUB_API,
    GitHubClient,
    STATUS_WEIGHTS,
    _is_self_fixed_issue,
    apply_overrides,
    build_generated_payload,
    build_search_query,
    fetch_activity,
    infer_status,
    is_maintainer_comment,
    normalize_search_item,
)
from scripts.render_open_source_signals import (
    build_project_groups,
    format_stars,
    render_svg,
    select_projects,
    truncate_text,
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

    def test_fix_keywords_include_required_terms(self):
        required_keywords = {
            "fixed",
            "fix",
            "resolved",
            "merged",
            "released",
            "addressed",
            "done",
            "已修复",
            "已合并",
            "已处理",
            "修复了",
        }
        self.assertTrue(required_keywords.issubset(set(FIX_KEYWORDS)))

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
        self.assertEqual(normalized["state"], "open")
        self.assertIsNone(normalized["repo_stars"])

    def test_generated_payload_wraps_activities_with_metadata(self):
        activities = [{"url": "https://github.com/o/r/issues/1"}]
        payload = build_generated_payload(
            username="Miracle778",
            activities=activities,
            generated_at="2026-06-21T15:00:00Z",
        )
        self.assertEqual(payload["generated_at"], "2026-06-21T15:00:00Z")
        self.assertEqual(payload["username"], "Miracle778")
        self.assertEqual(payload["activities"], activities)

    def test_search_pagination_caps_at_ten_full_pages(self):
        client = FakeGitHubClient({
            page: [{"id": f"item-{page}-{index}"} for index in range(100)]
            for page in range(1, 12)
        })
        items = client.get_all_pages(f"{GITHUB_API}/search/issues", {"q": "author:Miracle778"})
        self.assertEqual(len(items), 1000)
        self.assertEqual(client.requested_pages, list(range(1, 11)))

    def test_non_search_pagination_continues_until_partial_page(self):
        client = FakeGitHubClient({
            1: [{"id": f"item-1-{index}"} for index in range(100)],
            2: [{"id": f"item-2-{index}"} for index in range(99)],
        })
        items = client.get_all_pages(f"{GITHUB_API}/repos/o/r/issues/1/comments")
        self.assertEqual(len(items), 199)
        self.assertEqual(client.requested_pages, [1, 2])

    def test_open_issue_cross_referenced_by_user_pr_is_not_self_fixed(self):
        activity = {"type": "Issue", "state": "open"}
        timeline_events = [{
            "event": "cross-referenced",
            "source": {"issue": {
                "user": {"login": "Miracle778"},
                "state": "open",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/1"},
            }},
        }]
        self.assertFalse(_is_self_fixed_issue(activity, timeline_events, "Miracle778"))

    def test_non_merged_user_pr_reference_is_not_self_fixed(self):
        activity = {"type": "Issue", "state": "closed"}
        timeline_events = [{
            "event": "cross-referenced",
            "source": {"issue": {
                "user": {"login": "Miracle778"},
                "state": "closed",
                "pull_request": {
                    "url": "https://api.github.com/repos/o/r/pulls/1",
                    "merged_at": None,
                },
            }},
        }]
        self.assertFalse(_is_self_fixed_issue(activity, timeline_events, "Miracle778"))

    def test_closed_user_pr_reference_without_merge_metadata_is_not_self_fixed(self):
        activity = {"type": "Issue", "state": "closed"}
        timeline_events = [{
            "event": "cross-referenced",
            "source": {"issue": {
                "user": {"login": "Miracle778"},
                "state": "closed",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/1"},
            }},
        }]
        self.assertFalse(_is_self_fixed_issue(activity, timeline_events, "Miracle778"))

    def test_fetch_activity_caches_repo_stars_per_repo(self):
        client = FakeActivityClient()
        activities = fetch_activity({
            "profile": {"username": "Miracle778"},
            "display": {"lookback_days": None},
            "filters": {"include_types": ["PR"], "exclude_repos": []},
            "featured_repos": [],
            "overrides": {},
        }, client)

        self.assertEqual(len(activities), 2)
        self.assertEqual([activity["repo_stars"] for activity in activities], [4400, 4400])
        self.assertEqual(client.repo_detail_calls, 1)

    def test_fetch_activity_keeps_self_fixed_issues_for_stats(self):
        client = FakeSelfFixedActivityClient()
        activities = fetch_activity({
            "profile": {"username": "Miracle778"},
            "display": {"lookback_days": None},
            "filters": {"include_types": ["Issue"], "exclude_repos": []},
            "featured_repos": [],
            "overrides": {},
        }, client)

        self.assertEqual(len(activities), 1)
        self.assertTrue(activities[0]["self_fixed"])


class FakeGitHubClient(GitHubClient):
    def __init__(self, pages):
        self.pages = pages
        self.requested_pages = []

    def get(self, url, params=None):
        page = (params or {}).get("page", 1)
        self.requested_pages.append(page)
        page_items = self.pages.get(page, [])
        if "/search/issues" in url:
            return {"items": page_items}
        return page_items


class FakeActivityClient:
    def __init__(self):
        self.repo_detail_calls = 0

    def get_all_pages(self, url, params=None):
        if url == f"{GITHUB_API}/search/issues":
            return [
                self._item(1, "First PR"),
                self._item(2, "Second PR"),
            ]
        if url.endswith("/comments") or url.endswith("/timeline"):
            return []
        return []

    def get(self, url, params=None):
        if url == f"{GITHUB_API}/repos/o/r":
            self.repo_detail_calls += 1
            return {"stargazers_count": 4400}
        if url.endswith("/pulls/1") or url.endswith("/pulls/2"):
            return {"merged_at": None}
        return {}

    def _item(self, number, title):
        return {
            "html_url": f"https://github.com/o/r/pull/{number}",
            "repository_url": f"{GITHUB_API}/repos/o/r",
            "title": title,
            "number": number,
            "state": "open",
            "created_at": "2026-06-01T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z",
            "closed_at": None,
            "comments_url": f"{GITHUB_API}/repos/o/r/issues/{number}/comments",
            "timeline_url": f"{GITHUB_API}/repos/o/r/issues/{number}/timeline",
            "pull_request": {"url": f"{GITHUB_API}/repos/o/r/pulls/{number}"},
        }


class FakeSelfFixedActivityClient:
    def get_all_pages(self, url, params=None):
        if url == f"{GITHUB_API}/search/issues":
            return [{
                "html_url": "https://github.com/o/r/issues/1",
                "repository_url": f"{GITHUB_API}/repos/o/r",
                "title": "Issue fixed by own PR",
                "number": 1,
                "state": "closed",
                "created_at": "2026-06-01T00:00:00Z",
                "updated_at": "2026-06-02T00:00:00Z",
                "closed_at": "2026-06-02T00:00:00Z",
                "comments_url": f"{GITHUB_API}/repos/o/r/issues/1/comments",
                "timeline_url": f"{GITHUB_API}/repos/o/r/issues/1/timeline",
            }]
        if url.endswith("/comments"):
            return []
        if url.endswith("/timeline"):
            return [{
                "event": "cross-referenced",
                "source": {"issue": {
                    "user": {"login": "Miracle778"},
                    "pull_request": {"merged_at": "2026-06-02T00:00:00Z"},
                }},
            }]
        return []

    def get(self, url, params=None):
        if url == f"{GITHUB_API}/repos/o/r":
            return {"stargazers_count": 123}
        return {}


class RenderOpenSourceSignalsTests(unittest.TestCase):
    def test_truncate_text_adds_ellipsis(self):
        self.assertEqual(truncate_text("abcdef", 4), "abc…")
        self.assertEqual(truncate_text("abc", 4), "abc")

    def test_format_stars(self):
        self.assertEqual(format_stars(None), "")
        self.assertEqual(format_stars(999), "999")
        self.assertEqual(format_stars(1234), "1.2k")
        self.assertEqual(format_stars(72200), "72.2k")

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

    def test_featured_repos_follow_yaml_order(self):
        activities = [
            {"repo": "repo/b", "type": "PR", "status": "merged", "title": "Newer", "url": "https://github.com/repo/b/pull/1", "updated_at": "2026-06-21T00:00:00Z", "date": "2026-06", "featured": False},
            {"repo": "repo/a", "type": "Issue", "status": "open", "title": "Older", "url": "https://github.com/repo/a/issues/1", "updated_at": "2025-01-01T00:00:00Z", "date": "2025-01", "featured": False},
            {"repo": "new/repo", "type": "PR", "status": "merged", "title": "Outside", "url": "https://github.com/new/repo/pull/1", "updated_at": "2026-06-22T00:00:00Z", "date": "2026-06", "featured": False},
        ]
        groups = build_project_groups(activities, featured_repos=["repo/a", "repo/b"])
        repos = [group["repo"] for group in select_projects(groups, max_projects=5, max_items_per_project=3)]

        self.assertEqual(repos, ["repo/a", "repo/b", "new/repo"])

    def test_non_featured_repos_sort_by_total_count(self):
        activities = [
            {"repo": "repo/two", "type": "PR", "status": "merged", "title": "A", "url": "https://github.com/repo/two/pull/1", "updated_at": "2026-06-21T00:00:00Z", "date": "2026-06", "featured": True},
            {"repo": "repo/two", "type": "Issue", "status": "merged", "title": "B", "url": "https://github.com/repo/two/issues/2", "updated_at": "2026-06-20T00:00:00Z", "date": "2026-06", "featured": False},
            {"repo": "repo/three", "type": "Issue", "status": "closed", "title": "C", "url": "https://github.com/repo/three/issues/1", "updated_at": "2026-01-03T00:00:00Z", "date": "2026-01", "featured": False},
            {"repo": "repo/three", "type": "Issue", "status": "closed", "title": "D", "url": "https://github.com/repo/three/issues/2", "updated_at": "2026-01-02T00:00:00Z", "date": "2026-01", "featured": False},
            {"repo": "repo/three", "type": "Issue", "status": "closed", "title": "E", "url": "https://github.com/repo/three/issues/3", "updated_at": "2026-01-01T00:00:00Z", "date": "2026-01", "featured": False},
        ]
        groups = build_project_groups(activities, featured_repos=[])
        repos = [group["repo"] for group in select_projects(groups, max_projects=5, max_items_per_project=3)]

        self.assertEqual(repos[:2], ["repo/three", "repo/two"])

    def test_non_featured_repos_with_same_total_sort_by_timeline_date(self):
        activities = [
            {"repo": "repo/old", "type": "PR", "status": "merged", "title": "A", "url": "https://github.com/repo/old/pull/1", "updated_at": "2026-06-21T00:00:00Z", "date": "2025-01", "featured": True},
            {"repo": "repo/old", "type": "Issue", "status": "merged", "title": "B", "url": "https://github.com/repo/old/issues/2", "updated_at": "2026-06-20T00:00:00Z", "date": "2025-01", "featured": False},
            {"repo": "repo/new", "type": "Issue", "status": "closed", "title": "C", "url": "https://github.com/repo/new/issues/1", "updated_at": "2026-01-03T00:00:00Z", "date": "2026-06", "featured": False},
            {"repo": "repo/new", "type": "Issue", "status": "closed", "title": "D", "url": "https://github.com/repo/new/issues/2", "updated_at": "2026-01-02T00:00:00Z", "date": "2026-06", "featured": False},
        ]
        groups = build_project_groups(activities, featured_repos=[])
        repos = [group["repo"] for group in select_projects(groups, max_projects=5, max_items_per_project=3)]

        self.assertEqual(repos[:2], ["repo/new", "repo/old"])

    def test_render_svg_shows_repo_stars_in_project_title(self):
        groups = build_project_groups([{
            "repo": "o/r",
            "repo_stars": 4400,
            "type": "PR",
            "status": "merged",
            "title": "Add feature",
            "url": "https://github.com/o/r/pull/1",
            "date": "2026-06",
            "created_at": "2026-06-01T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z",
            "featured": False,
        }], featured_repos=[])
        svg = render_svg(select_projects(groups, 5, 3), title="Open Source Activity", theme="dark")

        self.assertIn("o/r · 4.4k", svg)

    def test_render_svg_shows_stats_icons(self):
        groups = build_project_groups([{
            "repo": "o/r",
            "type": "PR",
            "status": "merged",
            "title": "Add feature",
            "url": "https://github.com/o/r/pull/1",
            "date": "2026-06",
            "created_at": "2026-06-01T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z",
            "featured": False,
        }], featured_repos=[])
        svg = render_svg(select_projects(groups, 5, 3), title="Open Source Activity", theme="dark")

        self.assertIn('class="stats-icon total"', svg)
        self.assertIn('class="stats-icon type"', svg)
        self.assertIn('class="stats-icon status"', svg)

    def test_project_stats_count_self_fixed_but_display_hides_it(self):
        groups = build_project_groups([
            {
                "repo": "o/r",
                "type": "PR",
                "status": "open",
                "title": "Open PR",
                "url": "https://github.com/o/r/pull/1",
                "date": "2026-06",
                "created_at": "2026-06-01T00:00:00Z",
                "updated_at": "2026-06-03T00:00:00Z",
                "featured": False,
                "self_fixed": False,
            },
            {
                "repo": "o/r",
                "type": "Issue",
                "status": "fixed",
                "title": "Self fixed issue",
                "url": "https://github.com/o/r/issues/1",
                "date": "2026-06",
                "created_at": "2026-06-01T00:00:00Z",
                "updated_at": "2026-06-02T00:00:00Z",
                "featured": False,
                "self_fixed": True,
            },
        ], featured_repos=[])
        svg = render_svg(select_projects(groups, 5, 3), title="Open Source Activity", theme="dark")

        self.assertIn("Total 2", svg)
        self.assertIn("PR 1 · Issue 1", svg)
        self.assertIn("Fixed 1", svg)
        self.assertIn("Open 1", svg)
        self.assertIn("Open PR", svg)
        self.assertNotIn("Self fixed issue", svg)

    def test_render_svg_has_title_and_no_forbidden_elements(self):
        svg = render_svg([], title="Open Source Activity", theme="dark")
        self.assertIn("Open Source Activity", svg)
        self.assertIn("No open source activity found yet.", svg)
        self.assertNotIn("<script", svg)
        self.assertNotIn("foreignObject", svg)

    def test_render_svg_uses_created_month_for_timeline_date(self):
        groups = build_project_groups([{
            "repo": "o/r",
            "type": "Issue",
            "status": "fixed",
            "title": "Old issue fixed later",
            "url": "https://github.com/o/r/issues/1",
            "date": "2025-01",
            "created_at": "2025-01-14T00:00:00Z",
            "updated_at": "2026-06-21T00:00:00Z",
            "featured": False,
        }], featured_repos=[])
        selected = select_projects(groups, max_projects=5, max_items_per_project=3)
        svg = render_svg(selected, title="Open Source Activity", theme="dark")

        self.assertIn("2025-01", svg)
        self.assertNotIn("2026-06", svg)


if __name__ == "__main__":
    unittest.main()
