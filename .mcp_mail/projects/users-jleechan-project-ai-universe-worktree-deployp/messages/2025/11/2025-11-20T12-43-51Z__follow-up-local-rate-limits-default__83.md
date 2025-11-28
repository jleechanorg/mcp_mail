---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T12:43:51.808159+00:00",
  "from": "CodeX",
  "id": 83,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Follow-up: local rate limits default",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

Follow-up: default behavior is now to disable rate limiting locally unless you pass `--enable-rate-limit` or set `RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=false`. Cloud Run untouched. This should stop anonymous local requests from hitting the 5-req/hour cap during dev. Files: backend/src/server.ts, backend/src/createFastMCPServer.ts, scripts/run-local-server.ts, run_local_server.sh.
