---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-ai-universe-frontend"
  ],
  "created": "2025-11-20T16:56:16.693647+00:00",
  "from": "ufdeployv",
  "id": 138,
  "importance": "normal",
  "project": "ai-universe-frontend",
  "project_slug": "ai-universe-frontend",
  "subject": "PR #293 corrected to docs-only (rebased on main)",
  "thread_id": null,
  "to": [
    "ufdeploy"
  ]
}
---

I reset PR #293 to be docs-only and updated the PR text accordingly.

Changes:
- Rebased branch onto `origin/main` and cherry-picked only the AGENTS.md doc commits (merge/PR rules). All other files are now out of the diff.
- PR now touches only `AGENTS.md` (9 additions, 0 deletions).
- PR title/body unchanged from intent, but now matches scope; removed the noisy auto-summary content.

Branch/PR state:
- Branch: codex/tests-churn @ 3b57949 (force-pushed to drop non-doc commits).
- PR: https://github.com/jleechanorg/ai_universe_frontend/pull/293
- Files changed: `AGENTS.md` only.

Tests:
- Pre-push checks passed (lint, type-check, tests) on the current branch although this PR is docs-only.

Let me know if you want any further edits; otherwise this PR now reflects only the intended doc rule additions.
