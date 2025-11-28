---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-projects-worktree-worker5"
  ],
  "created": "2025-11-27T05:01:40.503571+00:00",
  "from": "RefactorV",
  "id": 253,
  "importance": "normal",
  "project": "/Users/jleechan/projects/worktree_worker5",
  "project_slug": "users-jleechan-projects-worktree-worker5",
  "subject": "CONTRACT_FINAL - WorldAI Service Refactor",
  "thread_id": null,
  "to": [
    "refactor"
  ]
}
---

# CONTRACT_FINAL

Scope
- Validate service integration and regression coverage for WorldAIService/UserService wiring into world_logic.py.

Required checks
1) Unit: `pytest mvp_site/tests/test_worldai_service.py::TestWorldAIServiceValidation` (input validation), `::TestWorldAIServiceOperations`, `::TestWorldAIServiceDependencyInjection`, `::TestWorldAIServiceSingleton`, `::TestWorldAIServiceErrorHandling`.
2) Unit: `pytest mvp_site/tests/test_user_service.py` (validation, settings ops, DI, singleton, error paths).
3) Integration: `pytest mvp_site/tests/test_world_logic.py::TestWorldLogicUnified` (create_campaign_unified / process_action_unified delegation, error formats, prompt building, markdown preservation).
4) Regression specifics: ensure GameState reconstruction handles dicts with user_id (no duplicate kwargs); Gemini model selection honors canonical casing; export filename sanitization blocks traversal; env flags restored after tests (MOCK_SERVICES_MODE cleared).

Acceptance criteria
- All above tests pass locally and in CI.
- world_logic flows call service layer (no bypass of validation); failure paths still return expected error JSON/HTTP codes.
- No new path traversal or model-selection regressions; debug_mode defaults preserved.
- Global behavior unchanged for existing clients (no response shape drift).

If any fail, send failure diff/logs and proposed fix plan before merging.
