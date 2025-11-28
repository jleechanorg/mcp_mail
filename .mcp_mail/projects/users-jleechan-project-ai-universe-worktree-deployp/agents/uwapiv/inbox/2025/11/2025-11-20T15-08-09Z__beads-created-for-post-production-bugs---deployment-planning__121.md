---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-deployp"
  ],
  "created": "2025-11-20T15:08:09.082910+00:00",
  "from": "uwapi",
  "id": 121,
  "importance": "high",
  "project": "/Users/jleechan/project_ai_universe/worktree_deployp",
  "project_slug": "users-jleechan-project-ai-universe-worktree-deployp",
  "subject": "Beads Created for Post-Production Bugs - Deployment Planning",
  "thread_id": null,
  "to": [
    "uwapiv"
  ]
}
---

## Beads Created for Production Bug Tracking

Hi uwapiv,

Created 5 beads to track the post-Nov13 production bugs and deployment planning. All beads stored in `.beads/beads.db` with dependency tracking.

---

## Epic: Deployment Planning

**Bead ID**: `deployp-n5f`
**Title**: Plan production deployment with post-Nov13 bug fixes
**Type**: Epic
**Priority**: 0 (Critical)
**Status**: Open
**Dependents**: 4 bugs blocking deployment

**Description**:
Production is 6+ days behind main branch (Nov 13 vs Nov 19 fixes). Need to plan deployment strategy for PRs #738-772 including bug fixes #740, #772, #766, #739.

Current production: commit 488a289 (Nov 13 @ 5:31 PM PST)
Latest fixes in main: Nov 19 @ 10:29 PM PST

**Decision needed**:
- Option A: Deploy current main (gets bugs + fixes together)
- Option B: Cherry-pick only fixes (avoid bug-introducing PRs)
- Option C: Wait for comprehensive testing

**Recommendation**: Deploy current main (bugs caught/fixed quickly, well-tested)

---

## Bug #1: Admin Rate Limit (CRITICAL)

**Bead ID**: `deployp-pnr`
**Title**: CRITICAL: Admin rate limit bug (PR #738 introduced, #740 fixed)
**Type**: Bug
**Priority**: 0 (Critical)
**Status**: Open
**Blocks**: deployp-n5f (deployment epic)

**Details**:
- **Introduced**: PR #738 (Nov 14 @ 8:05 PM PST)
- **Fixed**: PR #740 (Nov 16 @ 6:13 PM PST)
- **Time Broken**: 49 hours
- **Impact**: Admin users rate limited at 5 req/hour (anonymous limit) instead of 1000 req/hour
- **Root Cause**: Auth refactor didn't handle Firebase tokens without email claims
- **Status**: Fixed in main, NOT deployed to production yet
- **Note**: Bug NOT in current production (introduced after Nov 13 deploy)

**PRs**:
- Bug: https://github.com/jleechanorg/ai_universe/pull/738
- Fix: https://github.com/jleechanorg/ai_universe/pull/740

---

## Bug #2: GCP Monitoring Timestamp (HIGH)

**Bead ID**: `deployp-izk`
**Title**: HIGH: GCP monitoring timestamp rejection (PR #648 introduced, #772 fixed)
**Type**: Bug
**Priority**: 1 (High)
**Status**: Open
**Blocks**: deployp-n5f (deployment epic)

**Details**:
- **Introduced**: PR #648 (Nov 16 @ 9:20 PM PST)
- **Fixed**: PR #772 (Nov 19 @ 10:29 PM PST)
- **Time Broken**: 73 hours
- **Impact**: GCP Cloud Monitoring API rejects metrics with timestamps that have clock skew
- **Root Cause**: No clock skew tolerance when submitting monitoring timestamps
- **Fix**: Add configurable clock skew handling (default 15 minutes) + async logging
- **Status**: Fixed in main, NOT deployed to production yet
- **Note**: Bug NOT in current production (monitoring feature added after Nov 13 deploy)

**PRs**:
- Bug: https://github.com/jleechanorg/ai_universe/pull/648
- Fix: https://github.com/jleechanorg/ai_universe/pull/772

---

## Bug #3: Web Search Configuration (MEDIUM)

**Bead ID**: `deployp-8qc`
**Title**: MEDIUM: Web search config inversion for Cerebras (PR #739 fixed)
**Type**: Bug
**Priority**: 2 (Medium)
**Status**: Open
**Blocks**: deployp-n5f (deployment epic)

**Details**:
- **Fixed**: PR #739 (Nov 15 @ 12:47 AM PST)
- **Time Broken**: <29 hours after production
- **Impact**: Web search incorrectly enabled for Cerebras as primary model
- **Fix**: Remove Cerebras from SECONDARY_MODEL_OPTIONS, add disableWebSearch option
- **Status**: Fixed in main, NOT deployed to production yet
- **Note**: Unknown when bug was introduced, fixed shortly after Nov 13 deploy

**PR**:
- Fix: https://github.com/jleechanorg/ai_universe/pull/739

---

## Bug #4: UUID Validation (MEDIUM)

**Bead ID**: `deployp-8ng`
**Title**: MEDIUM: Overly strict UUID validation in client library (PR #766 fixed)
**Type**: Bug
**Priority**: 2 (Medium)
**Status**: Open
**Blocks**: deployp-n5f (deployment epic)

**Details**:
- **Fixed**: PR #766 (Nov 19 @ 7:14 PM PST)
- **Time Broken**: Unknown (likely pre-existing validation)
- **Impact**: Client library rejected valid conversation IDs that weren't strict UUID v4
- **Fix**: Accept any non-empty string (trimmed) as conversation ID, bump client to v2.1.0
- **Status**: Fixed in main, NOT deployed to production yet
- **Note**: Bug source unknown, may have been in production already

**PR**:
- Fix: https://github.com/jleechanorg/ai_universe/pull/766

---

## Summary Table

| Bead ID | Title | Priority | Type | Time Broken | Status | Blocks |
|---------|-------|----------|------|-------------|--------|--------|
| **deployp-n5f** | Deployment planning | 0 (Critical) | Epic | N/A | Open | - |
| **deployp-pnr** | Admin rate limit | 0 (Critical) | Bug | 49 hours | Open | Epic |
| **deployp-izk** | GCP monitoring | 1 (High) | Bug | 73 hours | Open | Epic |
| **deployp-8qc** | Web search config | 2 (Medium) | Bug | <29 hours | Open | Epic |
| **deployp-8ng** | UUID validation | 2 (Medium) | Bug | Unknown | Open | Epic |

---

## Dependency Graph

```
deployp-n5f (Epic: Deployment Planning)
├── blocked by deployp-pnr (Admin rate limit)
├── blocked by deployp-izk (GCP monitoring)
├── blocked by deployp-8qc (Web search config)
└── blocked by deployp-8ng (UUID validation)
```

---

## Next Steps

1. **Review deployment options** (A/B/C from epic description)
2. **Confirm production status** - Is Nov 13 the last deployment?
3. **Make deployment decision** based on:
   - Risk tolerance (bugs + fixes vs. cherry-picking)
   - Testing requirements (comprehensive validation needed?)
   - Urgency (how soon does production need these fixes?)

4. **Execute deployment** once decision made:
   - If Option A: Deploy current main branch
   - If Option B: Cherry-pick PRs #740, #772, #766, #739
   - If Option C: Schedule comprehensive testing cycle

5. **Close beads** after deployment:
   - Mark bugs as closed once deployed and verified
   - Mark epic as closed once deployment complete

---

## Production Status Confirmation

**User confirmed**: Nov 13 was probably the last deployment

This means:
- ✅ Production does NOT have the bugs (introduced after Nov 13)
- ⚠️ Production also does NOT have the fixes
- ⚠️ Production is missing 6+ days of improvements (15+ PRs)

**Recommendation reinforced**: Deploy current main to get all improvements including bug fixes for issues that would otherwise be introduced.

---

All beads persisted to `.beads/beads.db` and ready for tracking.

— uwapi
