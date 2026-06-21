import fs from "node:fs";
import { fileURLToPath } from "node:url";

const token = process.env.GITHUB_TOKEN;
const username = process.env.GITHUB_USERNAME || process.env.GITHUB_REPOSITORY_OWNER;
const limit = Number(process.env.CONTRIBUTION_LIMIT || 8);

const query = `
  query($query: String!, $limit: Int!) {
    search(query: $query, type: ISSUE, first: $limit) {
      nodes {
        __typename
        ... on Issue {
          title
          url
          state
          createdAt
          stateReason
          comments {
            totalCount
          }
          closedByPullRequestsReferences(first: 3) {
            nodes {
              number
              url
              author {
                login
              }
            }
          }
          timelineItems(last: 10, itemTypes: [CLOSED_EVENT]) {
            nodes {
              __typename
              ... on ClosedEvent {
                actor {
                  login
                }
              }
            }
          }
          repository {
            nameWithOwner
            url
            stargazerCount
          }
        }
        ... on PullRequest {
          title
          url
          state
          merged
          createdAt
          totalCommentsCount
          comments {
            totalCount
          }
          mergedBy {
            login
          }
          closingIssuesReferences(first: 3) {
            nodes {
              number
              url
              author {
                login
              }
            }
          }
          repository {
            nameWithOwner
            url
            stargazerCount
          }
        }
      }
    }
  }
`;

function escapeCell(value) {
  return String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
}

function formatStars(count) {
  if (count >= 10000) return `${(count / 1000).toFixed(1)}k`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return String(count);
}

export function statusOf(item) {
  if (item.__typename === "PullRequest" && item.merged) {
    return "Merged";
  }

  return item.state[0] + item.state.slice(1).toLowerCase();
}

export function signalOf(item, username) {
  if (item.__typename === "PullRequest") {
    if (item.merged) return "Accepted";
    if (item.state === "OPEN") return "In review";
    return "Closed";
  }

  if (item.state === "OPEN") {
    return item.comments?.totalCount > 0 ? "Discussed" : "Open";
  }

  const closingPrs = item.closedByPullRequestsReferences?.nodes?.filter(Boolean) ?? [];
  const nonSelfClosingPr = closingPrs.find((pr) => pr.author?.login !== username);
  if (nonSelfClosingPr) {
    return `Fixed by PR #${nonSelfClosingPr.number}`;
  }

  const selfClosingPr = closingPrs.find((pr) => pr.author?.login === username);
  if (selfClosingPr) {
    return "Self fixed";
  }

  const closeEvents = item.timelineItems?.nodes?.filter((node) => node?.__typename === "ClosedEvent") ?? [];
  const closeActor = closeEvents.at(-1)?.actor?.login;
  if (closeActor === username) {
    return "Closed by self";
  }

  if (item.stateReason === "COMPLETED") {
    return "Completed by maintainer";
  }

  if (item.stateReason === "NOT_PLANNED") {
    return "Not planned by maintainer";
  }

  return closeActor ? "Closed by maintainer" : "Closed";
}

function discussionCountOf(item) {
  if (item.__typename === "PullRequest") {
    return item.totalCommentsCount ?? item.comments?.totalCount ?? 0;
  }

  return item.comments?.totalCount ?? 0;
}

function shouldShowContribution(item, username) {
  return !(item.__typename === "Issue" && signalOf(item, username) === "Self fixed");
}

export function buildContributionsTable(nodes, username) {
  const rows = nodes.filter(Boolean).filter((item) => shouldShowContribution(item, username)).map((item) => {
  const repository = item.repository;
  const type = item.__typename === "PullRequest" ? "PR" : "Issue";
  const date = item.createdAt.slice(0, 10);

  return [
    date,
    `[${escapeCell(repository.nameWithOwner)}](${repository.url})`,
    formatStars(repository.stargazerCount),
    type,
    `[${escapeCell(item.title)}](${item.url})`,
    discussionCountOf(item),
    statusOf(item),
    signalOf(item, username),
  ].join(" | ");
}).map((row) => `| ${row} |`);

  return [
    "| Date | Repository | Stars | Type | Record | Discuss | Status | Signal |",
    "|---|---|---:|---|---|---:|---|---|",
    rows.length
      ? rows.join("\n")
      : "| - | 暂无公开记录 | - | - | 还没有拉取到公开 Issue / PR | - | - | - |",
  ].join("\n");
}

async function main() {
  if (!token) {
    throw new Error("Missing GITHUB_TOKEN");
  }

  if (!username) {
    throw new Error("Missing GITHUB_USERNAME or GITHUB_REPOSITORY_OWNER");
  }

  const response = await fetch("https://api.github.com/graphql", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      variables: {
        query: `author:${username} archived:false sort:created-desc`,
        limit,
      },
    }),
  });

  if (!response.ok) {
    throw new Error(`GitHub API failed: ${response.status} ${response.statusText}`);
  }

  const result = await response.json();

  if (result.errors) {
    throw new Error(JSON.stringify(result.errors, null, 2));
  }

  const table = buildContributionsTable(result.data.search.nodes, username);
  const links = [
    "",
    `[View all PRs](https://github.com/pulls?q=author%3A${username}) · [View all Issues](https://github.com/issues?q=author%3A${username})`,
  ].join("\n");

  const readme = fs.readFileSync("README.md", "utf8");
  const next = readme.replace(
    /<!-- CONTRIBUTIONS:START -->[\s\S]*?<!-- CONTRIBUTIONS:END -->/,
    `<!-- CONTRIBUTIONS:START -->\n${table}\n${links}\n<!-- CONTRIBUTIONS:END -->`,
  );

  fs.writeFileSync("README.md", next);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await main();
}
