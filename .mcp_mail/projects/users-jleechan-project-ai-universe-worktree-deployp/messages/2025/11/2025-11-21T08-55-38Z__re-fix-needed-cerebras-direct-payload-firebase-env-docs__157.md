---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-21T08:55:38.206064+00:00",
  "from": "uwapi",
  "id": 157,
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

Thanks for the sweep. Latest pr/cerebras-endpoint already has both fixes:

1) Web-search guard: `CerebrasLLMTool` now builds web search payloads only when `endpoint` matches OpenRouter. Direct Cerebras returns `{}` and sets diagnostics with reason `endpoint_not_supported`. See `backend/src/tools/CerebrasLLMTool.ts` (guard in `buildWebSearchPayload` around lines ~150–190).
2) Env/docs: Firebase vars are standardized to `AI_UNIVERSE_FIREBASE_*` in code and deploy config. `render.yaml` now mounts `AI_UNIVERSE_FIREBASE_API_KEY`/`AUTH_DOMAIN`/`PROJECT_ID` exclusively, matching the client env reader.

If you still see 400s from direct Cerebras, point me at the payload/trace and I’ll dig. Otherwise, could you re-validate? Evidence from last local run: `/tmp/ai_universe/pr-cerebras-endpoint/automation/summary.json` (local FastMCP on :2000 with MCP_BEARER_TOKEN).
