import assert from "node:assert/strict";
import test from "node:test";

import {
  buildContributionsTable,
  signalOf,
  statusOf,
} from "./update-contributions.mjs";

const username = "Miracle778";

test("buildContributionsTable removes Link column and adds Discuss and Signal", () => {
  const table = buildContributionsTable([
    {
      __typename: "PullRequest",
      title: "fix parser",
      url: "https://github.com/o/r/pull/1",
      state: "MERGED",
      merged: true,
      createdAt: "2026-01-02T00:00:00Z",
      comments: { totalCount: 2 },
      totalCommentsCount: 9,
      repository: {
        nameWithOwner: "o/r",
        url: "https://github.com/o/r",
        stargazerCount: 1234,
      },
    },
  ], username, 8);

  assert.match(table, /\| Date \| Repository \| Stars \| Type \| Record \| Discuss \| Status \| Signal \|/);
  assert.doesNotMatch(table, /\| Link \|/);
  assert.match(table, /\| 2026-01-02 \| \[o\/r\]\(https:\/\/github.com\/o\/r\) \| 1\.2k \| PR \| \[fix parser\]\(https:\/\/github.com\/o\/r\/pull\/1\) \| 9 \| Merged \| Accepted \|/);
});

test("buildContributionsTable hides issues that were self fixed", () => {
  const table = buildContributionsTable([
    {
      __typename: "PullRequest",
      title: "fix bug from my issue",
      url: "https://github.com/o/r/pull/10",
      state: "MERGED",
      merged: true,
      createdAt: "2026-01-03T00:00:00Z",
      comments: { totalCount: 1 },
      totalCommentsCount: 1,
      repository: {
        nameWithOwner: "o/r",
        url: "https://github.com/o/r",
        stargazerCount: 100,
      },
    },
    {
      __typename: "Issue",
      title: "bug I later fixed",
      url: "https://github.com/o/r/issues/9",
      state: "CLOSED",
      stateReason: "COMPLETED",
      createdAt: "2026-01-02T00:00:00Z",
      comments: { totalCount: 0 },
      closedByPullRequestsReferences: {
        nodes: [{
          number: 10,
          url: "https://github.com/o/r/pull/10",
          author: { login: username },
        }],
      },
      timelineItems: { nodes: [] },
      repository: {
        nameWithOwner: "o/r",
        url: "https://github.com/o/r",
        stargazerCount: 100,
      },
    },
  ], username, 8);

  assert.match(table, /fix bug from my issue/);
  assert.doesNotMatch(table, /bug I later fixed/);
  assert.doesNotMatch(table, /Self fixed/);
});

test("closed approved PR is Approved while merged PR stays Merged", () => {
  const approvedReview = {
    state: "APPROVED",
    authorAssociation: "MEMBER",
    author: { login: "maintainer" },
  };
  const closedApprovedPr = {
    __typename: "PullRequest",
    state: "CLOSED",
    merged: false,
    latestOpinionatedReviews: { nodes: [approvedReview] },
  };
  const mergedPr = {
    ...closedApprovedPr,
    state: "MERGED",
    merged: true,
  };

  assert.equal(statusOf(closedApprovedPr), "Approved");
  assert.equal(signalOf(closedApprovedPr, username), "Approved");
  assert.equal(statusOf(mergedPr), "Merged");
  assert.equal(signalOf(mergedPr, username), "Accepted");
});

test("signalOf summarizes issue closure reason and closing PR ownership", () => {
  assert.equal(signalOf({
    __typename: "Issue",
    state: "OPEN",
    stateReason: null,
    comments: { totalCount: 0 },
    closedByPullRequestsReferences: {
      nodes: [{
        number: 10,
        url: "https://github.com/o/r/pull/10",
        author: { login: username },
      }],
    },
    timelineItems: { nodes: [] },
  }, username), "Open");

  assert.equal(signalOf({
    __typename: "Issue",
    state: "CLOSED",
    stateReason: "COMPLETED",
    comments: { totalCount: 2 },
    closedByPullRequestsReferences: {
      nodes: [{
        number: 9,
        url: "https://github.com/o/r/pull/9",
        author: { login: "maintainer" },
      }],
    },
    timelineItems: { nodes: [] },
  }, username), "Fixed by PR #9");

  assert.equal(signalOf({
    __typename: "Issue",
    state: "CLOSED",
    stateReason: "NOT_PLANNED",
    comments: { totalCount: 0 },
    closedByPullRequestsReferences: { nodes: [] },
    timelineItems: {
      nodes: [{ __typename: "ClosedEvent", actor: { login: "maintainer" } }],
    },
  }, username), "Not planned by maintainer");

  assert.equal(signalOf({
    __typename: "Issue",
    state: "CLOSED",
    stateReason: "COMPLETED",
    comments: { totalCount: 0 },
    closedByPullRequestsReferences: {
      nodes: [{
        number: 10,
        url: "https://github.com/o/r/pull/10",
        author: { login: username },
      }],
    },
    timelineItems: { nodes: [] },
  }, username), "Self fixed");
});
