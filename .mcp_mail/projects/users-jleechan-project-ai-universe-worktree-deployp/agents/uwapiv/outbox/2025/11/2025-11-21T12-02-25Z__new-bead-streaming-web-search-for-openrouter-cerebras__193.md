---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-21T12:02:25.579156+00:00",
  "from": "uwapiv",
  "id": 193,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "New bead: streaming web-search for OpenRouter Cerebras",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

Created bead `deployp-ole` to track streaming web-search behavior for OpenRouter Cerebras. PR #774 currently disables web search on streaming calls routed through OpenRouter (callStream sets disableWebSearch=true). Need to confirm intended behavior; if streaming should allow web search, adjust CerebrasLLMTool and add tests/evidence.
