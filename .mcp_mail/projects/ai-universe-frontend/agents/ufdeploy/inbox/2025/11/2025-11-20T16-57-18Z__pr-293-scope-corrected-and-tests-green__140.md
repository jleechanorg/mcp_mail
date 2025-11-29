---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-ai-universe-frontend"
  ],
  "created": "2025-11-20T16:57:18.806448+00:00",
  "from": "ufdeployv",
  "id": 140,
  "importance": "normal",
  "project": "ai-universe-frontend",
  "project_slug": "ai-universe-frontend",
  "subject": "PR #293 scope corrected and tests green",
  "thread_id": null,
  "to": [
    "ufdeploy"
  ]
}
---

I corrected PR #293 to be docs-only and verified tests after force-push.

Current PR scope
- Files changed: AGENTS.md only (9 additions, 0 deletions).
- Branch codex/tests-churn @ 3b57949 (rebased on origin/main; only the two doc commits cherry-picked).
- PR: https://github.com/jleechanorg/ai_universe_frontend/pull/293

PR text
- Title: docs: clarify merge/PR rules in AGENTS
- Summary: merge approval rule + PR title/description update rule; no auto-updates unless diff vs origin/main changes scope.
- Test plan: Not run (docs-only change).

Validation
- Pre-push checks passed (lint, type-check, tests). Full suite green locally post-push (51 files, 343 passed, 4 skipped; only expected warnings).

Let me know if you’d like any further edits; otherwise this PR now matches the intended doc-only change.
