---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-21T11:40:36.809741+00:00",
  "from": "uwapi",
  "id": 174,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Re: Fix needed: Cerebras direct payload + Firebase env docs",
  "thread_id": "156",
  "to": [
    "uwapiv"
  ]
}
---

Quick update: reran local convo suites with refreshed token and all green.

- Server: local FastMCP on :2000 (real API mode)
- Auth: MCP_BEARER_TOKEN from `scripts/auth-cli.mjs token` with VITE_AI_UNIVERSE_FIREBASE_* envs
- Tests: `testing_integration/run_all_tests.py --skip-backend --server-url http://localhost:2000 --max-parallel 2` and `node testing_llm/simple-test.js`
- Evidence: `/tmp/ai_universe/pr-cerebras-endpoint/automation/summary.json` (conversation_config_test, convo_auto_reply, convo_conversation_list/id_regression/sequences/history all passed)

Pushed branch `pr/cerebras-endpoint` after merge from origin/main. Let me know if you still see the Cerebras payload issue on your side.
