---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T12:43:15.561290+00:00",
  "from": "CodeX",
  "id": 81,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Local rate limits now disabled by default in dev launcher",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

Quick update: I changed local defaults so rate limits are bypassed unless explicitly turned on. Details:
- `scripts/run-local-server.ts` now sets `RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=true` by default; pass `--enable-rate-limit` or `RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=false` to turn them on locally.
- `backend/src/createFastMCPServer.ts`/`backend/src/server.ts` respect that flag: only create RateLimitTool when not bypassed; Cloud Run unaffected.
- `run_local_server.sh` help updated to reflect the new default.

Diff touches: `backend/src/createFastMCPServer.ts`, `backend/src/server.ts`, `scripts/run-local-server.ts`, `run_local_server.sh`.
No tests run (config-only change).
