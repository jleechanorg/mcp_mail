---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-ai-universe"
  ],
  "created": "2025-11-21T06:51:20.768857+00:00",
  "from": "uwai",
  "id": 148,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/ai_universe",
  "project_slug": "users-jleechan-project-ai-universe-ai-universe",
  "subject": "Integration run results + secondary defaults/validation updates",
  "thread_id": null,
  "to": [
    "uwaiv"
  ]
}
---

Summary of latest changes (branch `claude/fix-backend-bugs-01VoNvgSHTZ922jRpxjrUqo5`):
- Secondary defaults restored to Grok+2 via `selectDefaultSecondaryModels`; regression test enforces 3-model plan. Evidence: /tmp/ai_universe/claude-fix-backend-bugs-01VoNvgSHTZ922jRpxjrUqo5/evidence/secondary_models_{red,green}.txt
- Client `conversationId` validation now matches backend (any non-empty trimmed string). Follow-up Bead: ai_universe-pd6 to decide long-term contract.

Real-mode integration run (CI_SIMULATION=false):
- Command: `TEST_OUTPUT_TYPE=integration_real python testing_integration/run_all_tests.py --server-url http://localhost:2000/mcp --conversation-url http://localhost:2000 --env CI_SIMULATION=false --backend-script /Users/jleechan/project_ai_universe/ai_universe/run_local_server.sh`
- Outputs in /tmp/dev1763670336/integration_real
  - Passed: conversation_config_test, convo_auto_reply, convo_conversation_list, convo_conversation_id_regression
  - Failed: convo_conversation_sequences (rateLimitExceeded on agent_second_opinion), convo_conversation_history (conversation.send-message response missing conversationId)
  - Summary: /tmp/dev1763670336/integration_real/summary.json
  - Logs: stdout/stderr per test under same dir; backend.log shows server on port 2484, using real secrets and remote convo backend.

Manual smokes:
- `node testing_llm/server-health.js` ✅
- `node testing_llm/simple-test.js` ✅

Next actions I suggest (not executed yet):
1) Reset rate limit counters or raise limits before rerunning convo_conversation_sequences; consider CI_SIMULATION switch or userId rotation to avoid false rate-limit failures.
2) Investigate missing conversationId in `conversation.send-message` response seen by `convo_conversation_history` (see stderr in integration_real/convo_conversation_history/stderr.log).
