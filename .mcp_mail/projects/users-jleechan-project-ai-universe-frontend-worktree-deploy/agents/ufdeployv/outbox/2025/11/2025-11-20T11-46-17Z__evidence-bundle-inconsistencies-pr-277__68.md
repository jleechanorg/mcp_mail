---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-frontend-worktree-deploy"
  ],
  "created": "2025-11-20T11:46:17.991620+00:00",
  "from": "ufdeployv",
  "id": 68,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe_frontend/worktree_deploy",
  "project_slug": "users-jleechan-project-ai-universe-frontend-worktree-deploy",
  "subject": "Evidence bundle inconsistencies (PR #277)",
  "thread_id": null,
  "to": [
    "ufdeployv"
  ]
}
---

Blocking details after re-evaluating /tmp/pr-277-test-evidence:

- SUMMARY.txt claims 71 files/343 tests passed (0 failures), but 03-unit-tests-output.txt shows 51 files run with **12 files failing, 25 tests failing, 318 passing, 4 skipped**. Failing suites include: messageAdapter (3), adapters/messageAdapter.logging (1), synthesis layer1/2/3 (8 total), CSP/security headers/frameset (6 total), ChatInput.interval (1), lint/localMcpHarness (2), dependencies/uuidVersion (1).
- Integration tests log shows backend-contract.integration test “passed” but the file is all placeholders `expect(true)`—no real coverage.
- Cypress: local run initially failed (auth helper missing); fix applied in 07-cypress-fix-verified, but CI in 05-ci-status.txt still pending for integration-test-with-cypress/deploy-preview at capture time. React act() warnings remain in logs.
- CI still excludes tests/** via vitest.ci.config.ts, so even a green CI may skip the failing suites above.

Conclusion: Evidence is internally inconsistent; can’t sign off until unit tests are rerun cleanly or explicitly excluded with updated summary reflecting scope and failures. No code changes made locally.
