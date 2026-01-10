# Cherry-Pick Plan for Upstream Commits

**Date:** 2025-11-29
**Branch:** claude/evaluate-repo-commits-01UdEHNJuCGFmaJLKzvhu1SQ

## Phase 1: Critical Bug Fixes and Type Safety (Low Risk)

### Batch 1A: Type Safety
```bash
git cherry-pick 042364c  # refactor: fix type annotations and improve type safety throughout codebase
```
**Validation:**
- Run `mypy src/mcp_agent_mail/`
- Run full test suite
- Check for any new type errors

### Batch 1B: Pathlib Consistency
```bash
git cherry-pick 9a530b2  # style: use pathlib for file opening in WSL2 detection test
```
**Validation:**
- Run affected tests
- Verify pathlib usage is consistent

**Risk:** LOW
**Estimated Time:** 30 minutes
**Blocker for:** None

---

## Phase 2: Git Hook Chain-Runner (Medium Risk)

### Batch 2A: Hook Chain-Runner
```bash
git cherry-pick 62dae16  # feat: implement composition-safe Git hook chain-runner with pathspec matching
```
**Validation:**
- Test hook installation: `mcp-agent-mail guard install`
- Verify chain-runner works with existing hooks
- Test Windows compatibility (if applicable)
- Verify pathspec library integration
- Run guard tests

**Risk:** MEDIUM (modifies Git hooks behavior)
**Estimated Time:** 1-2 hours
**Blocker for:** Pre-push guard enhancements

**Potential Conflicts:**
- `.github/workflows/` files
- `src/mcp_agent_mail/guard.py`
- `pyproject.toml` dependencies

---

## Phase 3: Product Bus (Medium Risk)

### Batch 3A: Product Bus Foundation
```bash
git cherry-pick 502e402  # feat: implement Product Bus with cross-project inbox and thread summarization
```
**Validation:**
- Test new CLI commands:
  - `mcp-agent-mail products ensure MyProduct --name "Test Product"`
  - `mcp-agent-mail products link MyProduct /path/to/project`
  - `mcp-agent-mail products status MyProduct`
  - `mcp-agent-mail products inbox MyProduct TestAgent`
  - `mcp-agent-mail products summarize-thread MyProduct THREAD-1`
- Run integration tests
- Verify MCP tools: `fetch_inbox_product`, `summarize_thread_product`
- Test cross-project message aggregation

**Risk:** MEDIUM (new feature, substantial code)
**Estimated Time:** 2-3 hours
**Blocker for:** Product-level coordination features

**Potential Conflicts:**
- `src/mcp_agent_mail/app.py`
- `src/mcp_agent_mail/cli.py`
- `AGENTS.md`, `README.md`

---

## Phase 4: Database Performance (Medium Risk)

### Batch 4A: Materialized Views and Optimization
```bash
git cherry-pick d8fadf5  # Optimize case-insensitive search with derived lowercase columns
git cherry-pick 20054f3  # Add materialized view optimization, longest-first sorting, and chunk checksums
git cherry-pick a6647eb  # Relocate ANALYZE to finalize_snapshot and add checksum tests
git cherry-pick 0e010ca  # Add test coverage for create_performance_indexes function
```
**Validation:**
- Run database migration tests
- Benchmark search performance before/after
- Verify materialized views are created correctly
- Run all database-related tests
- Check for schema conflicts

**Risk:** MEDIUM (database schema changes)
**Estimated Time:** 2-3 hours
**Blocker for:** Performance-sensitive deployments

**Potential Conflicts:**
- Database schema files
- Migration scripts
- Search-related code

---

## Phase 5: Enhanced Installer and Tooling (Medium Risk)

### Batch 5A: Installer Improvements
```bash
git cherry-pick 99a9a52  # Installer + docs improvements
```
**Validation:**
- Test one-line installer:
  - `curl -fsSL <url> | bash -s -- --yes --dry-run`
- Verify Beads CLI integration
- Test port configuration
- Verify docs helper: `mcp-agent-mail docs insert-blurbs`
- Test PATH wiring

**Risk:** MEDIUM (installation workflow changes)
**Estimated Time:** 1-2 hours
**Blocker for:** None

**Potential Conflicts:**
- `scripts/install.sh`
- `src/mcp_agent_mail/cli.py`
- `README.md`

---

## Phase 6: Disaster Recovery (Medium Risk)

### Batch 6A: Archive System
```bash
git cherry-pick da21d0f  # feat: add disaster-recovery archives
```
**Validation:**
- Test archive workflow:
  - `mcp-agent-mail archive save`
  - `mcp-agent-mail archive list`
  - `mcp-agent-mail archive restore`
- Run integration tests: `tests/integration/test_archive_workflow.py`
- Verify scrub preset preserves correct data
- Test clear-and-reset with archive prompts

**Risk:** MEDIUM (new feature with data handling)
**Estimated Time:** 2 hours
**Blocker for:** Production data safety

**Potential Conflicts:**
- `src/mcp_agent_mail/cli.py`
- `src/mcp_agent_mail/share.py`
- `.gitignore`

---

## Phase 7: Build Slots (Low-Medium Risk)

### Batch 7A: Build Slot System
```bash
git cherry-pick af7afbf  # feat: implement build slots for coarse-grained concurrency control
git cherry-pick 6f71735  # feat: add gate enforcement and robust filesystem safety to build slots
git cherry-pick 35329f1  # feat: implement full build slot lifecycle management in am-run wrapper
git cherry-pick 5cae428  # feat: add server integration to am-run, guard hints, and comprehensive test coverage
```
**Validation:**
- Test build slot lifecycle:
  - `acquire_build_slot`
  - `renew_build_slot`
  - `release_build_slot`
- Test conflict detection
- Test am-run integration
- Run build slot tests

**Risk:** LOW-MEDIUM (new feature, advisory only)
**Estimated Time:** 2-3 hours
**Blocker for:** None

**Potential Conflicts:**
- `src/mcp_agent_mail/app.py`
- `AGENTS.md`, `README.md`

---

## Phase 8: Test Reliability and CI (Low Risk)

### Batch 8A: Test Improvements
```bash
git cherry-pick 80efc34  # feat: add static export compatibility for viewer smoke tests
git cherry-pick 0c8dd3d  # refactor: inline guard conflict detection and improve snapshot/test robustness
git cherry-pick a0ca172  # fix: improve test reliability and guard hook advisory mode forwarding
```
**Validation:**
- Run full test suite
- Verify test stability (run 3x)
- Check CI workflows
- Verify guard tests pass

**Risk:** LOW
**Estimated Time:** 1 hour
**Blocker for:** None

---

## Phase 9: Agent Name Validation (Low Risk)

### Batch 9A: Name Validation
```bash
git cherry-pick 992202a  # refactor: consolidate docs and fix scrub logic to preserve agent names
git cherry-pick 560534b  # fix: set AGENT_NAME in E2E test for proper guard conflict detection
git cherry-pick 9831eb4  # fix: use valid adjective+noun agent name in E2E test
git cherry-pick 3e8ac62  # fix: replace all invalid agent names with valid adjective+noun pseudonyms
```
**Validation:**
- Verify agent name generation
- Run agent registration tests
- Check E2E tests

**Risk:** LOW
**Estimated Time:** 30 minutes
**Blocker for:** None

---

## Phase 10: Documentation and Discovery (Low Risk)

### Batch 10A: Discovery and CI
```bash
git cherry-pick d41d54b  # feat: add discovery YAML, GIT_IDENTITY_ENABLED alias, and CI workflow
git cherry-pick 33bc0f0  # docs: update PLAN to reflect completed canonicalizer test coverage
```
**Validation:**
- Verify discovery YAML works
- Check CI workflow integration
- Review documentation changes

**Risk:** LOW
**Estimated Time:** 30 minutes
**Blocker for:** None

---

## Phase 11: Docker Support (Optional - Medium Risk)

### Batch 11A: Docker
```bash
git cherry-pick 120430d  # feat: add production Docker support and fix GitLab subgroup URL normalization
```
**Validation:**
- Build Docker image
- Test container deployment
- Verify GitLab URL normalization

**Risk:** MEDIUM (if Docker is used in production)
**Estimated Time:** 1-2 hours
**Blocker for:** Containerized deployments

---

## NOT RECOMMENDED (High Risk / Low Value)

### Worktree Integration (Phase 1)
**Reason:** Substantial feature set requiring extensive validation. Evaluate need first.
**Commits:** 17bb76e, 4f403be, 9e4e5b1, 595face, and 10+ others
**Risk:** HIGH
**Alternative:** Create separate evaluation branch if worktree features are needed

### Share/Export System Enhancements
**Reason:** Lower priority unless sharing workflows are actively used
**Commits:** 94e15b6, 8661b72, 549f506, etc.
**Risk:** MEDIUM

### UI Enhancements
**Reason:** Cosmetic improvements, not critical functionality
**Commits:** 9192b45, d089685, 2c68b1c, 45266e8, 4b30b78, eb1c409, 8f494fd
**Risk:** LOW-MEDIUM

---

## Execution Strategy

### Recommended Order
1. **Phase 1** (Type Safety) - Immediate
2. **Phase 2** (Hook Chain-Runner) - After Phase 1 validates
3. **Phase 8** (Test Reliability) - After Phase 2
4. **Phase 3** (Product Bus) - After tests are stable
5. **Phase 4** (Database Performance) - After Product Bus
6. **Phase 6** (Disaster Recovery) - After database changes
7. **Phase 5** (Enhanced Installer) - After core features
8. **Phase 9** (Agent Name Validation) - Anytime after Phase 1
9. **Phase 10** (Documentation) - Anytime after Phase 1
10. **Phase 7** (Build Slots) - Optional, based on need
11. **Phase 11** (Docker) - Optional, if containerization needed

### General Cherry-Pick Process

For each phase:

```bash
# 1. Ensure clean working directory
git status

# 2. Cherry-pick the commit(s)
git cherry-pick <commit-sha>

# 3. If conflicts occur:
git status
# Resolve conflicts manually
git add <resolved-files>
git cherry-pick --continue

# 4. Run validation tests
pytest tests/
mypy src/mcp_agent_mail/

# 5. Test specific features
# (see validation steps for each phase)

# 6. Commit results
git add .
git commit -m "Cherry-pick: <feature description>"
```

### Conflict Resolution Tips

1. **Always prefer current fork's changes for:**
   - `.github/workflows/` configurations
   - Environment-specific settings
   - Custom test fixtures

2. **Prefer upstream changes for:**
   - Core functionality improvements
   - Bug fixes
   - Type annotations
   - Documentation

3. **Merge carefully:**
   - Database schema changes
   - CLI command modifications
   - MCP tool signatures

### Rollback Plan

If a cherry-pick causes issues:

```bash
# Abort cherry-pick in progress
git cherry-pick --abort

# Or revert a completed cherry-pick
git revert <commit-sha>

# Or reset to before the cherry-pick
git reset --hard HEAD~1
```

---

## Tracking

### Completed Phases
- [ ] Phase 1: Type Safety
- [ ] Phase 2: Hook Chain-Runner
- [ ] Phase 3: Product Bus
- [ ] Phase 4: Database Performance
- [ ] Phase 5: Enhanced Installer
- [ ] Phase 6: Disaster Recovery
- [ ] Phase 7: Build Slots
- [ ] Phase 8: Test Reliability
- [ ] Phase 9: Agent Name Validation
- [ ] Phase 10: Documentation
- [ ] Phase 11: Docker Support

### Issues Encountered
(Document any issues during cherry-picking here)

---

## Success Criteria

- [ ] All tests pass after each phase
- [ ] No regressions in existing functionality
- [ ] New features work as documented
- [ ] CI/CD pipelines remain green
- [ ] Documentation is updated
- [ ] Team can validate changes in staging environment

---

## Estimated Total Time

**Minimum (Phases 1-6, 8-10):** 10-14 hours
**Maximum (All phases):** 16-22 hours

**Recommended timeline:**
- Week 1: Phases 1-3 (Foundation)
- Week 2: Phases 4-6 (Database and Recovery)
- Week 3: Phases 7-11 (Optional features)
