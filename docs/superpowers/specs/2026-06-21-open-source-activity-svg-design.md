# Open Source Activity SVG Design

## Goal

Add an automated GitHub Profile README module that fetches public GitHub contribution activity and renders it as a static SVG timeline.

The new SVG module replaces the current table as the main `Open Source Activity` display. The existing Markdown contribution table is kept as a folded full log.

## Confirmed Decisions

- Use a new Python pipeline for the SVG feature.
- Keep the existing Node workflow for the full Markdown table.
- Render two SVG themes:
  - `assets/open-source-signals-dark.svg`
  - `assets/open-source-signals-light.svg`
- SVG title is exactly `Open Source Activity`.
- SVG has no subtitle.
- YAML config is not a complete activity data source. It stores profile, display, filters, featured repo ordering, and manual overrides.
- `featured_repos` is only a sorting boost, not an allowlist. New repos can still be rendered.
- Default lookback covers all available records by using `lookback_days: null`.
- Default project limit is 5.
- Default contribution display limit per project is 3.
- Tags are not shown.
- No large language model classification is used.
- No JavaScript, `foreignObject`, external font, or external image is used in SVG output.

## File Layout

New or changed files:

```text
README.md
data/open-source-signals.yml
data/open-source-signals.generated.json
scripts/fetch_github_activity.py
scripts/render_open_source_signals.py
assets/open-source-signals-dark.svg
assets/open-source-signals-light.svg
requirements.txt
.github/workflows/update-open-source-signals.yml
docs/superpowers/specs/2026-06-21-open-source-activity-svg-design.md
```

Existing files kept:

```text
scripts/update-contributions.mjs
scripts/update-contributions.test.mjs
.github/workflows/update-contributions.yml
```

## Configuration

`data/open-source-signals.yml` stores configuration and manual corrections:

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

The fetch script uses:

- `profile.username`
- `display.lookback_days`
- `filters.include_types`
- `filters.exclude_repos`
- `overrides`

The render script uses:

- `display.title`
- `display.max_projects`
- `display.max_items_per_project`
- `featured_repos`
- `overrides.featured`
- `overrides.title`
- `overrides.status`

## Fetch Pipeline

`scripts/fetch_github_activity.py`:

1. Read `data/open-source-signals.yml`.
2. Read `GITHUB_TOKEN` from the environment.
3. Query GitHub REST Search API for user-authored PRs and Issues:
   - `author:Miracle778 type:pr`
   - `author:Miracle778 type:issue`
4. If `lookback_days` is a number, add a `created:>=YYYY-MM-DD` qualifier. If it is `null`, do not apply a created-date filter.
5. Respect `include_types` and `exclude_repos`.
6. For each activity, fetch normalized details:
   - repo
   - type
   - title
   - number
   - URL
   - state
   - created/updated/closed timestamps
   - PR `merged_at`
   - comments
   - Issue timeline events
7. Infer status.
8. Apply YAML overrides by `html_url`.
9. Write `data/open-source-signals.generated.json`.

Generated JSON shape:

```json
{
  "generated_at": "2026-06-21T00:00:00Z",
  "username": "Miracle778",
  "activities": [
    {
      "date": "2026-06",
      "repo": "bytedance/deer-flow",
      "type": "PR",
      "title": "Expose authenticated runtime context in GuardrailRequest",
      "status": "merged",
      "url": "https://github.com/bytedance/deer-flow/pull/3665",
      "number": 3665,
      "created_at": "2026-06-20T00:00:00Z",
      "updated_at": "2026-06-21T00:00:00Z",
      "closed_at": "2026-06-21T00:00:00Z",
      "merged_at": "2026-06-21T00:00:00Z",
      "featured": true
    }
  ]
}
```

## Status Inference

Status weights:

```python
STATUS_WEIGHTS = {
    "merged": 100,
    "fixed": 90,
    "accepted": 80,
    "replied": 60,
    "open": 40,
    "closed": 20,
    "unknown": 10,
}
```

PR base status:

- `merged_at != None` -> `merged`
- `state == "open"` -> `open`
- `state == "closed"` and no `merged_at` -> `closed`

Issue base status:

- `state == "open"` -> `open`
- `state == "closed"` -> `closed`

Maintainer replied heuristic:

- Applies to PRs and Issues.
- Comments are checked for a non-target-user, non-bot author.
- The comment author association must be one of:
  - `OWNER`
  - `MEMBER`
  - `COLLABORATOR`
- If matched, status can become `replied`.
- `replied` cannot override higher-priority statuses such as `merged`, `fixed`, or `accepted`.

Fixed by maintainer heuristic:

- Applies only to Issues.
- Issue must be closed.
- Condition A: Issue timeline has a `cross-referenced` event whose source is a PR.
- Condition B: A maintainer comment contains a fix keyword:
  - `fixed`
  - `fix`
  - `resolved`
  - `merged`
  - `released`
  - `addressed`
  - `done`
  - `已修复`
  - `已合并`
  - `已处理`
  - `修复了`
- If neither condition matches, a closed Issue remains `closed`.

Self-fixed Issue handling:

- If an Issue is closed by the user's own PR, it is not treated as a strong activity signal for the SVG.
- The corresponding PR can still be displayed.
- This avoids showing duplicated evidence for the same contribution.

Overrides:

- Overrides are keyed by `html_url`.
- `status`, `title`, and `featured` from YAML override inferred values.
- Overrides have the highest priority.

## Rendering Pipeline

`scripts/render_open_source_signals.py`:

1. Read `data/open-source-signals.yml`.
2. Read `data/open-source-signals.generated.json`.
3. If generated JSON is missing or empty, render an empty-state SVG.
4. Group activities by `repo`.
5. Sort projects.
6. Sort activities inside each project.
7. Select at most `max_projects` projects.
8. Select at most `max_items_per_project` activities per displayed project.
9. Compute right-side stats from all activities in the project, not only displayed items.
10. Render dark and light static SVGs.

Project sort order:

1. Repo appears in `featured_repos`.
2. Project contains at least one `featured: true` activity.
3. Project's highest status weight.
4. Project's most recent activity update timestamp.

Activity sort order:

1. `featured: true`.
2. Status weight.
3. Most recent `updated_at`.

## SVG Layout

The SVG is a static timeline card:

- Top title: `Open Source Activity`
- No subtitle.
- Left: date and timeline dot.
- Center: repo name and up to 3 activity titles.
- Right: stats card.

Each project stats card shows:

```text
Total 4
PR 2 · Issue 2
Merged 1 · Replied 2 · Open 1
```

Stats rules:

- Total counts all project activities.
- PR/Issue counts all project activities.
- Status counts all project activities.
- Status labels are title-cased.
- Long stats text is truncated or limited to the highest-priority status labels.

Text overflow handling:

- Long repo names are truncated.
- Long titles are truncated.
- Long stats are truncated or split into short lines.
- SVG height is computed from the number of rendered projects.

Theme rules:

- Dark SVG:
  - dark background
  - teal primary color
  - light text
  - rounded cards
  - left timeline
  - right stats card
- Light SVG:
  - light background
  - teal/blue-green primary color
  - dark text
  - rounded cards
  - left timeline
  - right stats card

Empty state:

```text
No open source activity found yet.
```

## README Integration

`README.md` keeps the section title:

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
existing generated Markdown table
<!-- CONTRIBUTIONS:END -->

</details>
```

The existing full table is not deleted. The existing workflow continues to update it.

## GitHub Actions

Add `.github/workflows/update-open-source-signals.yml`:

- Supports `workflow_dispatch`.
- Supports daily schedule.
- Uses `GITHUB_TOKEN`.
- Installs Python dependencies from `requirements.txt`.
- Runs fetch script.
- Runs render script.
- Commits changes if generated JSON, SVGs, or README changed.

The existing `.github/workflows/update-contributions.yml` remains active and continues updating the folded full log.

## Error Handling

Fetch script:

- Missing `GITHUB_TOKEN`: exit with a clear error.
- GitHub API failure: exit with status code and response details.
- Rate limit response: exit with a clear rate-limit message.
- Empty API results: write generated JSON with an empty `activities` list.

Render script:

- Missing generated JSON: render empty-state SVGs.
- Empty `activities`: render empty-state SVGs.
- Unknown status: use `unknown`.
- Long text: truncate safely.

## Dependencies

`requirements.txt` contains at least:

```text
PyYAML
requests
```

## Verification

Implementation is accepted when:

1. `python scripts/fetch_github_activity.py` can fetch GitHub data with `GITHUB_TOKEN`.
2. `data/open-source-signals.generated.json` is generated.
3. `python scripts/render_open_source_signals.py` runs successfully.
4. `assets/open-source-signals-dark.svg` is generated.
5. `assets/open-source-signals-light.svg` is generated.
6. SVG title is exactly `Open Source Activity`.
7. SVG has no subtitle.
8. SVG shows at most 5 projects.
9. SVG shows at most 3 activities per project.
10. Same-repo activities are grouped.
11. Right-side stats include Total, type counts, and status counts.
12. PR `merged` status is detected.
13. Maintainer replies are detected conservatively.
14. Fixed-by-maintainer Issues are detected conservatively.
15. YAML overrides can override status, title, and featured.
16. Tags are not shown.
17. README uses `<picture>` for dark/light SVGs.
18. Existing contribution table is preserved in a folded full log.
19. GitHub Actions can be manually triggered.
20. GitHub Actions can automatically commit generated JSON and SVG changes.
