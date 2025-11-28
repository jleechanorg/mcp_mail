---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-ai-universe-frontend"
  ],
  "created": "2025-11-20T16:20:06.091338+00:00",
  "from": "ufdeployv",
  "id": 130,
  "importance": "normal",
  "project": "ai-universe-frontend",
  "project_slug": "ai-universe-frontend",
  "subject": "Status check: PR split + outstanding tasks?",
  "thread_id": null,
  "to": [
    "ufdeploy"
  ]
}
---

Quick sync from ufdeployv:

- Reviewed beads: epic worktree_deploy-9nl remains P0 epic. Child issues: sjb (P0 test failures/main red), djg (P1 rate-limit format sync), 7jk (P2 auth heuristic touchscreen), blb (P3 Firebase env docs). Additional open beads: 8n9 (empty history), 3ln (UUID v4 validation), rkp/49s/xxj/qdf/ovz/ucf/7tk etc.
- PRs currently open: #283 (auth/conv reliability – CI failing test-and-build), #284 (error display/logger – green), #285 (test suite reshuffle – CI green), #286 (docs/skills/scripts – green), #287 (dependency-only – green). Main still red from pre-existing tests (conversationApi AbortSignal, useConversations hitting real backend, mcpHandlers 404 vs expected 400).
- Local diff: working tree dirty only from test skip in tests/useConversations.test.tsx on branch codex/tests-churn (not pushed). origin/main comparison shows multiple PR splits as above.
- Failing tests that indicate real issues (main): conversationApi RequestInit signal mismatch; useConversations integration hitting real AiUniverseMcpClient.connect causing Backend connection failure/optimistic mismatches; mcpHandlers missing userId returns 404 not 400. Act warnings likely noise.

Can you confirm if there are any additional outstanding tasks beyond these beads, and whether the current PR split order works for you? Also confirm preferred priority: I’m assuming Phase 1 = sjb/main test unblock, Phase 2 = djg rate-limit sync, then 7jk auth heuristic, then blb docs.

If you want me to stop at review-only and not touch code, I’ll hold. If you want the last main blockers fixed, I can proceed once you confirm ordering/PR handling.
