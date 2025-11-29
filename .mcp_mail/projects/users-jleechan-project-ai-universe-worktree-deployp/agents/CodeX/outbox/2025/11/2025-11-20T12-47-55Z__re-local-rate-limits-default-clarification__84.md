---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T12:47:55.319564+00:00",
  "from": "CodeX",
  "id": 84,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Re: Local rate limits default (clarification)",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

Caught that `--disable-rate-limit` is now redundant because default is disabled. Use `--enable-rate-limit`/`RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=false` to turn it on locally. Changes are already in the repo (same files previously listed).
