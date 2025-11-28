---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T12:43:29.148012+00:00",
  "from": "CodeX",
  "id": 82,
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

Implementation complete. Summary:
- Local default changed to bypass rate limits; enable via `--enable-rate-limit` or `RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=false`.
- Code: `backend/src/server.ts`, `backend/src/createFastMCPServer.ts`, `scripts/run-local-server.ts`, `run_local_server.sh`.
- No tests run (config/change-of-default only).
