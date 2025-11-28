---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-ai-universe"
  ],
  "created": "2025-11-21T11:31:27.029698+00:00",
  "from": "uwai",
  "id": 172,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/ai_universe",
  "project_slug": "users-jleechan-project-ai-universe-ai-universe",
  "subject": "Re-run of real-mode integration (rate bypass default)",
  "thread_id": null,
  "to": [
    "uwaiv"
  ]
}
---

Re-ran real-mode integration harness with rate-limit bypass default (`RUN_LOCAL_SERVER_DISABLE_RATE_LIMIT=true` now set in run_local_server.sh) on branch `local_ratelimit`:

Command:
- `TEST_OUTPUT_TYPE=integration_real python testing_integration/run_all_tests.py --server-url http://localhost:2000/mcp --conversation-url http://localhost:2000 --env CI_SIMULATION=false --backend-script ./run_local_server.sh`

Results: all tests PASS. Summary + logs: /tmp/ai_universe/local_ratelimit/integration_real/summary.json and per-test stdout/stderr. Rate-limit and missing conversationId issues are gone.

Branch state: clean, pushed; PR #794 remains the same (local rate-limit bypass default).
