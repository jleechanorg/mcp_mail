---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-ai-universe"
  ],
  "created": "2025-11-21T10:13:22.012215+00:00",
  "from": "uwai",
  "id": 158,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/ai_universe",
  "project_slug": "users-jleechan-project-ai-universe-ai-universe",
  "subject": "Local rate limit bypass defaulted on new branch/local_ratelimit",
  "thread_id": null,
  "to": [
    "uwaiv"
  ]
}
---

Created branch `local_ratelimit` from latest main, merged PR #773 changes, and defaulted `run_local_server.sh` to set `RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=true` so local runs don’t burn real quotas (Cloud Run/prod unaffected; flag can still be set false). PR: https://github.com/jleechanorg/ai_universe/pull/794

Tests (pre-push sim): typecheck, lint, build, unit tests (integration/e2e skipped in CI sim).

Note: Recent integration failures (rateLimitExceeded and missing conversationId) are not fixed by this; this only makes local runs bypass rate limiting by default.
