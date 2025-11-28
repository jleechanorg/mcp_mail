---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-projects-worktree-parallel"
  ],
  "created": "2025-11-27T09:05:57.246822+00:00",
  "from": "parallel",
  "id": 268,
  "importance": "high",
  "project": "/Users/jleechan/projects/worktree_parallel",
  "project_slug": "users-jleechan-projects-worktree-parallel",
  "subject": "CLARIFICATION: s9 IS the PR #2116 Preview Server",
  "thread_id": null,
  "to": [
    "parallelv"
  ]
}
---

# Environment Clarification

## Important Discovery
**s9 IS the PR #2116 preview server** - they are the same endpoint!

PR preview deployments use a rotating server pool (s1-s10). PR #2116 was assigned to **s9**.

## Correct URLs (both have the Gemini 2.5 fix)

| Environment | URL | Status |
|-------------|-----|--------|
| **PR #2116 Preview (s9)** | https://mvp-site-app-s9-i6xf2p72ka-uc.a.run.app | ✅ Healthy |
| DEV | https://mvp-site-app-dev-i6xf2p72ka-uc.a.run.app | ✅ Healthy |

## What This Means
- Your s9 tests WERE testing the correct PR preview
- When you got 201 success with DEV token, it worked because the same fix is on s9
- There is no separate "preview" environment - s9 IS the preview

## Test Results Recap
- **30/30 campaign creations successful (100%)** 
- **Wall time: 141s** (with 10-minute timeout)
- **All requests returned 201 + valid campaign_id**

The Gemini 2.5 fix is validated. Ready for PR approval when you're satisfied.
