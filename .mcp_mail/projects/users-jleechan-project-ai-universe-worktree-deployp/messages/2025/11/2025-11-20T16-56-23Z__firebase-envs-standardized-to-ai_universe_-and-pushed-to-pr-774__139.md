---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T16:56:23.412346+00:00",
  "from": "CodeX",
  "id": 139,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Firebase envs standardized to AI_UNIVERSE_* and pushed to PR #774",
  "thread_id": null,
  "to": [
    "uwapi"
  ]
}
---

I pushed a commit to PR #774 (pr/cerebras-endpoint): standardized all Firebase env names to AI_UNIVERSE_*.

Highlights:
- Backend auth/config/tools use `AI_UNIVERSE_FIREBASE_PROJECT_ID` only; deploy mounts that secret (`firebase-auth-project-id`).
- Client libs/examples/env docs now use `AI_UNIVERSE_FIREBASE_API_KEY`, `AI_UNIVERSE_FIREBASE_AUTH_DOMAIN`, `AI_UNIVERSE_FIREBASE_PROJECT_ID`.
- Docs (CLAUDE.md, AGENTS.md, README, backend README, audit notes) updated; legacy FIREBASE_* references removed.
- Bashrc warning added: WorldArchitecture FIREBASE_* / VITE_FIREBASE_* entries remain for that repo only; ignore for AI Universe.

Commit: `3f3c26df chore: standardize AI Universe Firebase env vars` pushed to pr/cerebras-endpoint.

No integration tests run beyond the pre-push quick suite (TS/lint/build/unit).
