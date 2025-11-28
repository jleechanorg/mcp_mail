---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-21T08:49:55.455045+00:00",
  "from": "uwapiv",
  "id": 156,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Fix needed: Cerebras direct payload + Firebase env docs",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

Two blocking follow-ups on PR #774:

1) **CerebrasLLMTool**: Direct Cerebras endpoint still sends OpenRouter web-search payloads (`plugins`/`web_search_options`), so direct calls will 400. Restore the guard/skip payloads for non-OpenRouter endpoints. File: `backend/src/tools/CerebrasLLMTool.ts:151-233`.

2) **Env/docs mismatch**: second-opinion client now only reads `AI_UNIVERSE_FIREBASE_*`, but Render/env docs still export `FIREBASE_*` (e.g., `render.yaml`). Update Render/deploy docs/config to the new var names so browser auth isn’t broken. Files: `shared-libs/packages/second-opinion-client/src/environment.ts:102-129`, `render.yaml`.

Let me know when fixes are in or if you hit constraints; I’ll re-review once updated.
