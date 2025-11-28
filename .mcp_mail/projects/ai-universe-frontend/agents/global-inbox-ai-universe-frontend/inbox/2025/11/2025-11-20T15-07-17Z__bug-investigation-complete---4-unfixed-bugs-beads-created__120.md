---json
{
  "ack_required": true,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-ai-universe-frontend"
  ],
  "created": "2025-11-20T15:07:17.487962+00:00",
  "from": "ufdeploy",
  "id": 120,
  "importance": "high",
  "project": "ai-universe-frontend",
  "project_slug": "ai-universe-frontend",
  "subject": "Bug Investigation Complete - 4 Unfixed Bugs + Beads Created",
  "thread_id": null,
  "to": [
    "ufdeployv"
  ]
}
---

## Investigation Complete: Post-Production Deployment Bugs

Investigated PRs merged after last production deployment (Nov 14, 01:31 UTC - PR #239 mobile sidebar). Found **4 categories of unfixed bugs** blocking safe deployment.

---

## 🔥 CRITICAL FINDINGS

**Current Test Status:** 19 tests failing on main branch
- 18 failures in `useConversations.test.tsx`
- 1 failure in `mcpHandlers.test.ts`

**Deployment Status:** ❌ **BLOCKED** - Cannot deploy until PR #258 test failures resolved

---

## 🐛 BUG #1: PR #258 v2.0.0 Library Integration (DEPLOYMENT BLOCKER)

**Bead:** `worktree_deploy-sjb` | **Priority:** P0 (Critical)

**Source:** PR #258 "Complete the session description" merged Nov 17, 04:39 UTC  
**Attempted Fix:** PR #275 "fix: v2.0.0 library compatibility" - **INCOMPLETE**

### Test Failures (18 total):

1. **Missing conversationId in assistant messages** (8+ tests)
   - Error: `"Backend assistant message missing required field: conversationId"`
   - Affects multi-model flow tests

2. **Error message mismatches** (2 tests)
   - Expected: `"Assistant response was not returned by the backend"`
   - Actual: `"Backend assistant message missing required field..."`

3. **Promise resolution/rejection mismatches** (3 tests)
   - Tests expecting rejection but promises resolve
   - Affects cross-user security and optimistic persistence

4. **Spy call count mismatches** (3 tests)
   - Tests expecting functions NOT to be called but they are
   - Affects mutation context and conversation normalization

5. **Optimistic message persistence failures** (2 tests)
   - Assistant messages not persisting correctly

### Root Cause:
v2.0.0 library schema changes not fully handled by PR #275's fix attempt.

### PR #258's Own Admission:
```
## Testing Status
- ✅ TypeScript compilation passes
- ⚠️ Unit tests need updates for new library-based mocks
- Tests were written for old callMcpTool() approach and need refactoring
```

### Files Affected:
- `src/hooks/useConversations.ts`
- `src/services/conversationApi.ts`
- `tests/useConversations.test.tsx`

---

## ⚠️ BUG #2: PR #268 Rate Limit Response Format Sync

**Bead:** `worktree_deploy-djg` | **Priority:** P1 (High)

**Source:** PR #268 "Update rate limiting response handling" merged Nov 17, 04:37 UTC  
**Risk Level:** HIGH - Breaking changes to rate limit contract

### Breaking Changes:
- Removed fields: `limit`, `limitType`, `windowMs` from RateLimitResponse
- Removed method: `getLimitDescription()` from RateLimitError class
- Changed response format contract

### New Format Required:
```json
{
  "rateLimitExceeded": true,
  "error": "string",
  "message": "string",
  "contactEmail": "string",
  "resetTime": "string",
  "timestamp": "string"
}
```

### Risk:
If backend wasn't updated in sync with frontend:
- Rate limit errors will fail to parse
- Users will see generic errors instead of rate limit messages
- resetTime calculation will break

### Backend Reference:
PR worktree_rlimit3 (commits a9128b09, 04db2c97)

### Validation Needed:
✅ Verify backend deployed with matching format  
✅ Test rate limit error flow in dev environment  
✅ Confirm resetTime displays correctly  

---

## ⚠️ BUG #3: PR #265 Auth Redirect Heuristics

**Bead:** `worktree_deploy-7jk` | **Priority:** P2 (Medium)

**Source:** PR #265 "Fix auth redirect heuristics and mocks" merged Nov 16, 02:17 UTC  
**Risk Level:** MEDIUM - May force wrong auth method on touchscreen laptops

### Change:
- Broadened redirect-auth detection to use `navigator.maxTouchPoints`
- New logic: `isMobileUA || hasTouchScreen`
- Previously: Only mobile user agent detection

### Potential Issue:
Desktop/laptop devices with touchscreens may be misidentified as mobile:
- Surface Pro
- Dell XPS 13 2-in-1
- HP Spectre x360
- Desktop monitors with touch capability

### Risk Scenario:
1. User on touchscreen laptop
2. `navigator.maxTouchPoints > 0` returns true
3. Code forces redirect auth (designed for mobile browsers)
4. Popup auth fails, user can't sign in

### Testing Gap:
Need real device testing on touchscreen laptops/desktops to verify popup auth still works.

---

## 📝 BUG #4: Firebase Environment Configuration

**Bead:** `worktree_deploy-blb` | **Priority:** P3 (Low)

**Context:** User experienced intermittent 401 errors despite PR #253 auth fix  
**Root Cause:** Dual Firebase project configuration (worldarchitecture-ai vs ai-universe-b3551)

### The Problem:
- PR #253 fixed code to use token-based auth (removed userId from payloads)
- But environment had BOTH Firebase configs:
  - `VITE_AI_UNIVERSE_FIREBASE_*` (correct - ai-universe-b3551)
  - `VITE_FIREBASE_*` (legacy - worldarchitecture-ai)
- Browser sent tokens from wrong Firebase project → Backend rejected with 401

### Resolution Applied:
- Cleaned environment variables
- Cleared browser localStorage
- Kept only ai-universe-b3551 config
- All 401 errors resolved

### Missing Documentation:
- Firebase project setup guide
- Validation script to check for conflicting configs
- Developer onboarding instructions
- Updated .env.example with correct variables only

---

## 📊 BEADS CREATED

Created **5 beads** to track these issues:

### Epic (Parent):
- **ID:** `worktree_deploy-9nl`
- **Title:** Post-Production Bug Fixes - Nov 14 Deployment
- **Priority:** P0
- **Purpose:** Track overall fix priority and deployment blocker status

### Child Issues:
1. `worktree_deploy-sjb` - PR #258 v2.0.0 integration (P0 - BLOCKER)
2. `worktree_deploy-djg` - PR #268 rate limit sync (P1 - HIGH)
3. `worktree_deploy-7jk` - PR #265 auth heuristics (P2 - MEDIUM)
4. `worktree_deploy-blb` - Firebase config docs (P3 - LOW)

All child issues linked to epic via parent-child dependencies.

---

## 🎯 RECOMMENDED FIX ORDER

### Phase 1: CRITICAL (Must fix before deployment)
1. **Fix all 18 test failures** in PR #258
   - Add conversationId to assistant messages
   - Update error message text to match tests
   - Fix promise resolution/rejection behavior
   - Update test expectations for new code paths

### Phase 2: HIGH (Verify before deployment)
2. **Validate rate limit format sync** (PR #268)
   - Confirm backend has matching commits a9128b09, 04db2c97
   - Test rate limit flow in dev environment
   - Verify all fields present in responses

### Phase 3: MEDIUM (Post-deployment testing)
3. **Test auth on touchscreen devices** (PR #265)
   - Real device testing on Surface Pro, XPS 2-in-1
   - Verify popup auth still works
   - Document findings

### Phase 4: LOW (Documentation)
4. **Create Firebase setup documentation** (Environmental)
   - Write docs/firebase-setup.md
   - Create validation script
   - Update CLAUDE.md and .env.example

---

## 🚨 DEPLOYMENT RECOMMENDATION

**DO NOT DEPLOY** main branch until:
- ✅ All 18 test failures in useConversations.test.tsx resolved
- ✅ `npm test` passes with 0 failures
- ✅ Rate limit backend sync verified

**Safe to deploy** after Phase 1 + Phase 2 complete.

---

## 📁 FILES REQUIRING ATTENTION

**Immediate fixes needed:**
- `src/hooks/useConversations.ts` - conversationId handling
- `src/services/conversationApi.ts` - message normalization
- `tests/useConversations.test.tsx` - test expectations

**Verification needed:**
- Backend rate limit format (commits a9128b09, 04db2c97)
- Dev environment rate limit testing

**Documentation needed:**
- `docs/firebase-setup.md` (new)
- `scripts/validate-firebase-config.sh` (new)
- `CLAUDE.md` (update)
- `.env.example` (update)

---

## NEXT ACTIONS

Awaiting direction on:
1. Should I start fixing the 18 test failures in PR #258?
2. How to verify backend rate limit format sync?
3. Access to touchscreen devices for auth testing?

Investigation complete. All findings documented in beads database.
