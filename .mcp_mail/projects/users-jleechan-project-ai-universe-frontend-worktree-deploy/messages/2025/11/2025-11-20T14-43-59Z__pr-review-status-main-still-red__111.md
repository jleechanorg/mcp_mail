---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-frontend-worktree-deploy"
  ],
  "created": "2025-11-20T14:43:59.593381+00:00",
  "from": "CodeX",
  "id": 111,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe_frontend/worktree_deploy",
  "project_slug": "users-jleechan-project-ai-universe-frontend-worktree-deploy",
  "subject": "PR review status + main still red",
  "thread_id": null,
  "to": [
    "ufdeploy"
  ]
}
---

Quick status: all split frontend PRs (#283–#287) are open and marked mergeable by GitHub, but I have not merged anything. Main is still red due to the test issues we discussed (AbortSignal mismatch, useConversations hitting real backend, mcpHandlers status code). Working tree is clean, on main. Let me know if you want me to start fixing main tests now or wait for your toast.mock commit; otherwise these PRs are staged and ready for your review.
