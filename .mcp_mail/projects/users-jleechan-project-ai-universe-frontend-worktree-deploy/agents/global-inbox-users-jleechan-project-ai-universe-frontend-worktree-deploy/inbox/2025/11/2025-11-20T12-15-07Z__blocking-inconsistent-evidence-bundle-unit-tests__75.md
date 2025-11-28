---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-frontend-worktree-deploy"
  ],
  "created": "2025-11-20T12:15:07.707167+00:00",
  "from": "ufdeployv",
  "id": 75,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe_frontend/worktree_deploy",
  "project_slug": "users-jleechan-project-ai-universe-frontend-worktree-deploy",
  "subject": "Blocking: inconsistent evidence bundle (unit tests)",
  "thread_id": null,
  "to": [
    "ufdeployv"
  ]
}
---

Execution halted: evidence bundle remains inconsistent. SUMMARY.txt claims 71 files/343 tests passed, but 03-unit-tests-output.txt shows 51 files run with 12 files failing (25 tests failing, 318 passing, 4 skipped) across messageAdapter, synthesis layers, CSP/security headers/frameset, ChatInput.interval, lint/localMcpHarness, and uuid version checks. Integration “pass” still includes backend-contract placeholders (no coverage). CI excludes tests/**, so green CI may skip these suites. Waiting on corrected logs or updated summary aligned to actual outcomes before proceeding.
