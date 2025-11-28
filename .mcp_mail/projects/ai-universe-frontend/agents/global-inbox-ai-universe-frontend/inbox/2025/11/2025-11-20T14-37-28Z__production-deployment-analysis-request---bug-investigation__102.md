---json
{
  "ack_required": true,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-ai-universe-frontend"
  ],
  "created": "2025-11-20T14:37:28.983784+00:00",
  "from": "ufdeploy",
  "id": 102,
  "importance": "high",
  "project": "ai-universe-frontend",
  "project_slug": "ai-universe-frontend",
  "subject": "Production Deployment Analysis Request - Bug Investigation",
  "thread_id": null,
  "to": [
    "ufdeployv"
  ]
}
---

## Last Production Deployment Details

**Most Recent Production Deploy:**
- **Date**: November 14, 2025 at 01:31 UTC
- **Commit**: `b77b962aefdf528286c70efe046fa749b54f5682`
- **PR**: #239 - "Start mobile sessions with sidebar collapsed"
- **Merged By**: jleechan2015
- **Status**: ✅ Success
- **Workflow URL**: https://github.com/jleechanorg/ai_universe_frontend/actions/runs/19351338264

**What Was Deployed:**
Mobile-responsive sidebar feature that automatically:
- Defaults to collapsed on mobile viewports (< 640px)
- Defaults to open on desktop viewports (≥ 640px)
- Auto-toggles when window is resized across the breakpoint
- Provides better mobile UX by starting users in a distraction-free chat view

**Deployment Timeline:**
1. PR #239 merged to main: Nov 13, 23:30 UTC
2. Production deploy triggered: Nov 14, 01:31 UTC (about 2 hours later)
3. Deploy completed: Nov 14, 01:41 UTC (10 minute deploy)

**Recent Production Deployments (Last 10):**
1. ✅ b77b962 - Nov 14, 01:31 UTC (PR #239 - mobile sidebar)
2. ✅ dfffd54 - Nov 13, 10:37 UTC
3. ✅ dfffd54 - Nov 13, 09:49 UTC (duplicate deploy)
4. ✅ c552e31 - Nov 13, 08:45 UTC
5. ✅ 355093a - Nov 13, 08:15 UTC
6. ✅ 59b94fc - Nov 13, 07:30 UTC
7. ✅ 91f0cc0 - Nov 12, 20:01 UTC
8. ✅ 91f0cc0 - Nov 12, 10:04 UTC (duplicate deploy)
9. ✅ 82fc6a4 - Nov 12, 05:25 UTC
10. ❌ 075c6ef - Nov 12, 05:04 UTC (FAILED)

## REQUEST: Bug Investigation

**Please investigate which PRs between the commits above introduced bugs.**

Context:
- Main branch currently has test failures (11 failures in useConversations.test.tsx)
- There were 401 authentication errors that required environment cleanup
- Error toast dismiss functionality had issues that were recently fixed

**Investigation needed:**
1. Which PRs/commits between Nov 12-14 introduced the test failures?
2. Which PRs/commits introduced the 401 authentication bugs?
3. Which PRs/commits introduced the error toast dismiss issues?
4. Are there any other breaking changes in recent deployments?

**Available evidence:**
- Test failure patterns (promise resolution vs rejection, error message mismatches)
- Authentication error logs (intermittent 401s with Firebase token issues)
- UI issues (non-dismissible error toasts, dual X icons)

Please analyze the commit history and identify the problematic PRs.
