---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T11:13:45.483219+00:00",
  "from": "CodexDeploy",
  "id": 64,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Open work items snapshot (deployp)",
  "thread_id": null,
  "to": [
    "uwapiv"
  ]
}
---

Snapshot of current beads (all assigned to uwapi):

- `deployp-cbz` (P0 bug): Fix Firebase Admin SDK project to `ai-universe-b3551`; current aud mismatch blocks auth.
- `deployp-tae` (P1 task, blocked by cbz): Re-run 5 auth gap scenarios with fresh tokens; save evidence under /tmp/ai_universe/test_dev/auth_tests/.
- `deployp-1k1` (P2): Move HTTP/disk logging to async pipeline, keep /tmp evidence layout.
- `deployp-155` (P2): Restore CONVERSATION_MCP_SERVER_URL for PR previews so /smoke hits real APIs.
- `deployp-hq3` (P2): Validate Cerebras/OpenRouter web search behavior, capture HTTP evidence, recommend enabling/keeping plugin guard.
- `deployp-xa8` (P2): Duplicate of hq3; same validation/evidence needed.

Let me know if you need anything else bubbled up or dependencies added.
