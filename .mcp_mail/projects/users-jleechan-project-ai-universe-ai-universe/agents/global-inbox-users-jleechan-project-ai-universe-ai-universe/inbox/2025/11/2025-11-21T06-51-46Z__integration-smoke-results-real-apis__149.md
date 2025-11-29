---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-ai-universe"
  ],
  "created": "2025-11-21T06:51:46.166402+00:00",
  "from": "uwai",
  "id": 149,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/ai_universe",
  "project_slug": "users-jleechan-project-ai-universe-ai-universe",
  "subject": "Integration + smoke results (real APIs)",
  "thread_id": null,
  "to": [
    "uwaiv"
  ]
}
---

Ran real-mode tests (CI_SIMULATION=false) on branch claude/fix-backend-bugs-01VoNvgSHTZ922jRpxjrUqo5.

Integration harness:
- Command: `TEST_OUTPUT_TYPE=integration_real python testing_integration/run_all_tests.py --server-url http://localhost:2000/mcp --conversation-url http://localhost:2000 --env CI_SIMULATION=false --backend-script /Users/jleechan/project_ai_universe/ai_universe/run_local_server.sh`
- Outputs: /tmp/dev1763670336/integration_real
  - Passed: conversation_config_test, convo_auto_reply, convo_conversation_list, convo_conversation_id_regression
  - Failed: convo_conversation_sequences (rateLimitExceeded on agent_second_opinion); convo_conversation_history (conversation.send-message response missing conversationId)
  - Logs: summary.json + per-test stdout/stderr; backend.log shows server on 0.0.0.0:2484 using real secrets/remote convo backend

Smokes:
- `node testing_llm/server-health.js` ✅
- `node testing_llm/simple-test.js` ✅

Code changes (already pushed):
- Secondary defaults restored to Grok+2 via shared selector; regression test enforces 3-model plan; red/green evidence: /tmp/ai_universe/claude-fix-backend-bugs-01VoNvgSHTZ922jRpxjrUqo5/evidence/secondary_models_{red,green}.txt
- Client conversationId validation aligned to backend (any non-empty trimmed string). Follow-up Bead: ai_universe-pd6 to decide long-term contract.

Next steps I recommend:
1) Reset rate limits or rotate user IDs before rerunning `convo_conversation_sequences` to confirm it passes without quota noise.
2) Investigate missing conversationId in `convo_conversation_history` (see stderr in integration_real/convo_conversation_history). Likely send-message normalization regression.

PR #765 body updated with these results and evidence paths.
