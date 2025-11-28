---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-22T04:57:49.116714+00:00",
  "from": "uwapiv",
  "id": 206,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "PR 761 cherry-picks to salvage",
  "thread_id": null,
  "to": [
    "uwapiv"
  ]
}
---

Summary of what to cherry-pick (and what to avoid) from PR 761 `debug_convoh`:

**Keep / reimplement**
- Security: `AuthModeValidator` style behavior — never trust client `userId` for anonymous, require explicit `authMode`, generate server-side anonymous IDs, use `_authenticatedUserId` when present. Implement in current main without regressing newer logging/middleware changes.
- Dependency hygiene: `backend/src/test/PackageDependencyIntegrity.test.ts` plus associated dependency additions (`@modelcontextprotocol/sdk` devDep, `@ai-universe/typescript-server-launcher` file dep). Make sure test output goes under `/tmp/ai_universe/<branch>/...` per policy.

**Do NOT merge from 761**
- Massive deletions of workflows, skills docs, request logging middleware pruning, ConversationAgent message persistence verification removal. PR is stale and would roll back critical infra and fixes.

Next actions I recommend on a fresh branch off `main`:
1) Port a minimal `AuthModeValidator` with secure anonymous handling and wire it into ConversationAgent/SecondOpinionAgent; retire client-provided `userId` for anonymous.
2) Add dependency integrity test plus missing deps as above.
3) Leave everything else as-is on main (do not cherry-pick other 761 commits).

I have not applied changes; this is a salvage plan before moving on to PR 800 review feedback.
