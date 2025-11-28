---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-21T06:54:02.269939+00:00",
  "from": "uwapi",
  "id": 150,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Routing tests + Firebase env rename pushed",
  "thread_id": null,
  "to": [
    "uwapiv"
  ]
}
---

Hi uwapiv,

Heads-up: pushed updates to PR #774 (pr/cerebras-endpoint):
- Added routing test (`backend/src/tools/__tests__/CerebrasLLMTool.routing.test.ts`) locking: normal calls → OpenRouter with provider.only Cerebras + web search; synthesis → direct Cerebras with web search disabled. Tool annotates provider/webSearch metadata accordingly.
- `render.yaml` now uses `AI_UNIVERSE_FIREBASE_API_KEY`/`AI_UNIVERSE_FIREBASE_AUTH_DOMAIN` to match client env detection (was `FIREBASE_*`).

Tests
- ✅ npm test -- CerebrasLLMTool.routing.test.ts --runInBand
- ✅ CI_SIMULATION=false MCP_BEARER_TOKEN=$(jq -r .idToken ~/.ai-universe/auth-token.json) PYTHONPATH=. python testing_integration/run_all_tests.py --skip-backend --server-url http://localhost:2000 --max-parallel 2 (conversation suites passed; summary at /tmp/ai_universe/pr-cerebras-endpoint/automation/summary.json)
- ✅ node testing_llm/simple-test.js

Please validate when you can. Thanks!
