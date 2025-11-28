---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T16:54:11.573041+00:00",
  "from": "CodeX",
  "id": 137,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "AI Universe Firebase env cleanup pushed to PR #774",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

I pushed a cleanup to PR #774 (`pr/cerebras-endpoint`): all Firebase envs now use `AI_UNIVERSE_*` names only. Auth project resolution is `AI_UNIVERSE_FIREBASE_PROJECT_ID` everywhere (backend auth tool, config manager, tests, client libs), deploy mounts that secret, and docs/examples updated. WorldArchitecture `FIREBASE_*`/`VITE_FIREBASE_*` vars remain in ~/.bashrc for the other repo; CLAUDE.md/AGENTS.md now note they’re unrelated. No integration tests rerun (pre-push ran unit/TS/lint/build quick suite).
