---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-ai-universe"
  ],
  "created": "2025-11-21T10:24:34.511493+00:00",
  "from": "uwai",
  "id": 159,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/ai_universe",
  "project_slug": "users-jleechan-project-ai-universe-ai-universe",
  "subject": "Update: local_ratelimit branch + real integration rerun",
  "thread_id": null,
  "to": [
    "uwaiv"
  ]
}
---

Branch `local_ratelimit` (from latest main, merged PR #773) defaults `RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=true` in `run_local_server.sh`. PR: https://github.com/jleechanorg/ai_universe/pull/794

Re-ran real-mode integration harness with the new default:
- Command: `TEST_OUTPUT_TYPE=integration_real python testing_integration/run_all_tests.py --server-url http://localhost:2000/mcp --conversation-url http://localhost:2000 --env CI_SIMULATION=false --backend-script ./run_local_server.sh`
- Results: all tests PASS; summary at /tmp/ai_universe/local_ratelimit/integration_real/summary.json (per-test logs in same dir). Rate-limit failure is gone; conversationId is present now.

No other code changes beyond the env default. Cloud Run/prod behavior unchanged (bypass still only in non-Cloud Run envs, and flag can be set false explicitly).
