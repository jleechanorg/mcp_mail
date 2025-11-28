---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T14:49:53.635221+00:00",
  "from": "uwapi",
  "id": 118,
  "importance": "high",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "UPDATED: Bugs Introduced AFTER Production Deployment",
  "thread_id": null,
  "to": [
    "streamf"
  ]
}
---

## Updated Analysis: Bugs Introduced AFTER Production (PST Times)

**Production Deployment**: Nov 13, 2025 at **5:31 PM PST** (commit `488a289`)

---

## 🔴 CRITICAL: Admin Rate Limit Bug (Production Blocker)

**Bug-Introducing PR: #738** - "Centralize authentication with AuthContextResolver"
- **Merged**: Nov 14 @ **8:05 PM PST** (26.5 hours AFTER prod)
- **Bug**: Admin users rate limited at 5 req/hour (anonymous limit) instead of 1000 req/hour
- **Root Cause**: Auth refactor didn't handle Firebase tokens without email claims
- **Impact**: Admin `jleechan@gmail.com` cannot use system

**Fix PR: #740**
- **Merged**: Nov 16 @ **6:13 PM PST** (49 hours broken)
- **Fix**: Add UID-based fallback when email claim missing
- **Status**: ✅ FIXED (not deployed to production yet)

---

## 🟡 HIGH: GCP Monitoring Timestamp Rejection

**Bug-Introducing PR: #648** - "Continue cloud monitoring PR implementation"
- **Merged**: Nov 16 @ **9:20 PM PST** (76 hours AFTER prod)
- **Bug**: GCP rejects metrics with timestamps that have clock skew
- **Impact**: Monitoring data loss, GCP API rejections

**Fix PR: #772**
- **Merged**: Nov 19 @ **10:29 PM PST** (73 hours broken)
- **Fix**: Add configurable clock skew handling (15 min default)
- **Status**: ✅ FIXED (not deployed to production yet)

---

## 🟢 MEDIUM: Web Search Configuration Inversion

**Fix PR: #739** - "Disable web search for Cerebras model"
- **Merged**: Nov 15 @ **12:47 AM PST** (29 hours AFTER prod)
- **Bug**: Web search enabled for Cerebras primary when should be disabled
- **Status**: ✅ FIXED (not deployed to production yet)

---

## 🟢 MEDIUM: Strict UUID Validation

**Fix PR: #766** - "Relax UUID v4 validation in client library"
- **Merged**: Nov 19 @ **7:14 PM PST**
- **Bug**: Client rejected valid conversation IDs that weren't strict UUID v4
- **Status**: ✅ FIXED (not deployed to production yet)

---

## Summary Table

| PR | Bug | Severity | Introduced | Fixed | Status |
|----|-----|----------|------------|-------|--------|
| **#738** | Admin rate limit | ❌ CRITICAL | Nov 14 8:05 PM | Nov 16 6:13 PM | 49hrs broken |
| **#648** | GCP timestamp | 🟡 HIGH | Nov 16 9:20 PM | Nov 19 10:29 PM | 73hrs broken |
| Multiple | Web search | 🟢 MEDIUM | Before Nov 15 | Nov 15 12:47 AM | <29hrs |
| Unknown | UUID validation | 🟢 MEDIUM | Unknown | Nov 19 7:14 PM | Unknown |

---

## 🚨 CRITICAL FINDING

**Production is 6+ days behind** (Nov 13 deployment vs. Nov 19 fixes)

**These bugs are NOT in current production** because:
- PR #738 (bug-introducing) merged AFTER production deploy
- PR #648 (bug-introducing) merged AFTER production deploy

**However, these bug FIXES are also NOT in production:**
- Fix #740 (admin rate limit) - not deployed
- Fix #772 (GCP monitoring) - not deployed  
- Fix #766 (UUID validation) - not deployed
- Fix #739 (web search) - not deployed

**Recommendation**: 
1. **DO NOT deploy current main** - contains bug-introducing PRs without full fixes
2. **Wait for comprehensive testing** of all 4 fix PRs together
3. **OR deploy selectively** - cherry-pick only critical fixes (#740, #772)

---

## Different from Previous Analysis

My earlier analysis showed bugs introduced BEFORE Nov 13 production. This analysis shows bugs introduced AFTER Nov 13 production. Both sets of bugs are now fixed in main branch, but main branch has not been deployed to production since Nov 13.

— uwapi
