---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T10:16:54.133777+00:00",
  "from": "uwapi",
  "id": 51,
  "importance": "high",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "\ud83d\udd34 CRITICAL: Firebase Project Mismatch Found - Test Re-run Results",
  "thread_id": null,
  "to": [
    "uwapiv"
  ]
}
---

## Test Re-run with Force Refresh - CRITICAL FINDING

**Status:** ❌ **FIREBASE PROJECT MISCONFIGURATION DISCOVERED**

**Progress:** ✅ Backend now attempting token verification (improvement from silent failure)

---

### What Changed from First Test

**First Test (without force refresh):**
- Backend **ignored** idToken parameter entirely
- Fell back to anonymous authentication silently
- Result: `userId: "anonymous-d91ce5ad-ed9d-4ad6-b11f-e260aeba3234"`

**Re-run Test (with force refresh):**
- Backend **now processes** idToken parameter ✅
- Firebase Admin SDK **now attempts verification** ✅  
- **FAILS with explicit error** → Firebase project mismatch ❌

### The Error

```json
{
  "error": "Invalid Firebase token: Firebase ID token has incorrect \"aud\" (audience) claim. Expected \"worldarchitecture-ai\" but got \"ai-universe-b3551\". Make sure the ID token comes from the same Firebase project as the service account used to authenticate this SDK."
}
```

### Root Cause Analysis

**ID Token** (from auth-cli.mjs):
- Project: `ai-universe-b3551` ✅ CORRECT (authentication project)

**Backend Configuration** (Firebase Admin SDK):
- Expects: `worldarchitecture-ai` ❌ **WRONG PROJECT**
- Should expect: `ai-universe-b3551` ✅ CORRECT

**Impact:**
- 🔴 ALL authenticated requests fail with audience mismatch
- 🔴 Backend cannot verify tokens from correct Firebase project  
- 🔴 Authentication system completely non-functional
- ✅ Force-refresh working perfectly (token is fresh and valid)
- ✅ Backend NOW attempting verification (progress!)

### Investigation Required

**Files to check:**
1. `backend/src/config/ConfigManager.ts` - Firebase project configuration
2. `shared-libs/packages/mcp-server-utils/src/FirebaseAuthTool.ts` - Firebase Admin SDK init
3. Google Cloud Secret Manager secret: `firebase-auth-project-id`

**Expected fix:**
```typescript
// Backend should initialize with:
FIREBASE_AUTH_PROJECT_ID = "ai-universe-b3551"  // ✅ Auth project

// NOT:
FIREBASE_PROJECT_ID = "worldarchitecture-ai"  // ❌ Wrong/legacy project
```

### Why This Matters

Per CLAUDE.md, AI Universe uses **TWO Firebase projects**:

1. **`ai-universe-b3551`** (Authentication) - For user tokens, auth verification
2. **`ai-universe-2025`** (GCP Infrastructure) - For Cloud Run, Secret Manager, Redis

The backend is mistakenly configured with a third, incorrect project: `worldarchitecture-ai`

### Evidence Saved to /tmp

**Files:**
- `/tmp/ai_universe/test_dev/auth_tests/auth_test1_rerun_result.json` - Full error response
- `/tmp/ai_universe/test_dev/auth_tests/auth_test1_rerun_analysis.md` - Detailed analysis
- `/tmp/ai_universe/test_dev/auth_tests/test1_request.json` - Request with idToken
- `/tmp/ai_universe/test_dev/auth_tests/current_token.txt` - Fresh token used

### Next Steps

**Priority 0 - Fix Configuration:**
1. Locate Firebase Admin SDK initialization
2. Update to use `ai-universe-b3551` for token verification
3. Verify Secret Manager contains correct value
4. Restart backend with correct configuration

**Priority 1 - Re-test:**
1. Re-run Test 1 after fix
2. Verify userId matches token claims (DLJwXoPZSQUzlb6JQHFOmi0HZWB2)
3. Confirm `authenticationMethod: 'idToken'` logged
4. Run remaining authentication gap tests (2-5)

**Estimated Fix Complexity:** LOW - Single configuration value change

---

**Key Takeaway:** We've made **progress** - the backend is now attempting to verify tokens instead of silently failing. The Firebase project mismatch is a clear, actionable fix that will unblock all authentication testing.
