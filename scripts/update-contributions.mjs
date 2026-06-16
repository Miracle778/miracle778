import fs from "node:fs";

const token = process.env.GITHUB_TOKEN;
const username = process.env.GITHUB_USERNAME || process.env.GITHUB_REPOSITORY_OWNER;
const limit = Number(process.env.CONTRIBUTION_LIMIT || 8);

if (!token) {
  throw new Error("Missing GITHUB_TOKEN");
}

if (!username) {
  throw new Error("Missing GITHUB_USERNAME or GITHUB_REPOSITORY_OWNER");
}

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

function escapeCell(value) {
  return String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
}

function formatStars(count) {
  if (count >= 10000) return `${(count / 1000).toFixed(1)}k`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return String(count);
}

function statusOf(item) {
  if (item.__typename === "PullRequest" && item.merged) {
    return "Merged";
  }

  return item.state[0] + item.state.slice(1).toLowerCase();
}

const nodes = result.data.search.nodes.filter(Boolean);

const rows = nodes.map((item) => {
  const repository = item.repository;
  const type = item.__typename === "PullRequest" ? "PR" : "Issue";
  const date = item.createdAt.slice(0, 10);

  return [
    date,
    `[${escapeCell(repository.nameWithOwner)}](${repository.url})`,
    formatStars(repository.stargazerCount),
    type,
    `[${escapeCell(item.title)}](${item.url})`,
    statusOf(item),
    `[View](${item.url})`,
  ].join(" | ");
}).map((row) => `| ${row} |`);

const table = [
  "| Date | Repository | Stars | Type | Record | Status | Link |",
  "|---|---|---:|---|---|---|---|",
  rows.length
    ? rows.join("\n")
    : "| - | 暂无公开记录 | - | - | 还没有拉取到公开 Issue / PR | - | - |",
].join("\n");

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
