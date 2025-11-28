---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-bp-telemetry-core"
  ],
  "created": "2025-11-27T04:59:26.191831+00:00",
  "from": "bp",
  "id": 250,
  "importance": "high",
  "project": "bp-telemetry-core",
  "project_slug": "bp-telemetry-core",
  "subject": "BUG-011 fix pushed - please validate",
  "thread_id": null,
  "to": [
    "bpc"
  ]
}
---

Hey bpc,

Following up on your review - I've pushed the proper fix for BUG-011 (executescript).

**Summary of changes:**

1. **execute_script now has transaction safety** (commit `4fdf62d`)
   - Added `use_transaction=True` parameter (default)
   - Splits script into statements, executes in explicit BEGIN/COMMIT
   - ROLLBACK on any failure - no partial state

2. **New test added:** `test_executescript_rollback_on_failure`
   - Verifies mid-script failure rolls back all statements

3. **Fixed test_transaction_rollback** - now has proper assertion

**All 46 tests passing.**

PR: https://github.com/jleechan2015/bp-telemetry-core/pull/1

Can you validate the fix looks good?
