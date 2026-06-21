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
    infer_status,
    is_maintainer_comment,
    normalize_search_item,
)
from scripts.render_open_source_signals import (
    build_project_groups,
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


if __name__ == "__main__":
    unittest.main()
