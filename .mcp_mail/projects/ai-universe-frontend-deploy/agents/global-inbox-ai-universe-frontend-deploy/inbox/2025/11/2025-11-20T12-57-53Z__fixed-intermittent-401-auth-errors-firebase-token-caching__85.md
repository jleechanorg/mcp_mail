---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-ai-universe-frontend-deploy"
  ],
  "created": "2025-11-20T12:57:53.338933+00:00",
  "from": "ufdeploy",
  "id": 85,
  "importance": "high",
  "project": "ai-universe-frontend-deploy",
  "project_slug": "ai-universe-frontend-deploy",
  "subject": "Fixed: Intermittent 401 auth errors (Firebase token caching)",
  "thread_id": null,
  "to": []
}
---

## Fix Deployed

Successfully identified and fixed intermittent 401 authentication errors in the frontend.

### Problem
The `conversationApi.ts` cached `SecondOpinionClient` instances with Firebase ID tokens in headers. When tokens expired (1 hour lifetime), cached clients continued using expired tokens → intermittent 401 errors.

**Pattern**: 401 → 200 → 200 → 401

### Solution
Removed client caching entirely. Firebase's `getIdToken()` auto-refreshes expired tokens internally, so we always get valid tokens without manual caching.

### Changes
- Simplified `createAuthenticatedClient()` to always create fresh client
- Removed `cachedClient`, `cachedToken`, `cachedBaseUrl` state
- Added explanatory comments about Firebase's token management

### Testing
✅ Type-check passed  
✅ ESLint passed  
✅ 343 tests passed  
✅ Pre-commit and pre-push hooks passed  

### PR
https://github.com/jleechanorg/ai_universe_frontend/pull/281

### Beads Issue
Closed: `worktree_deploy-a0n`

---

**Agent**: ufdeploy (claude-code / claude-sonnet-4-5)  
**Session**: 2025-11-19
