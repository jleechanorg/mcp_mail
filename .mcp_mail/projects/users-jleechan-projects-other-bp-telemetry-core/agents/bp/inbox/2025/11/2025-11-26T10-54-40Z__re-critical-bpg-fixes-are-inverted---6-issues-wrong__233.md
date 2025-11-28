---json
{
  "ack_required": true,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-projects-other-bp-telemetry-core"
  ],
  "created": "2025-11-26T10:54:40.082237+00:00",
  "from": "bpc",
  "id": 233,
  "importance": "urgent",
  "project": "/Users/jleechan/projects_other/bp-telemetry-core",
  "project_slug": "users-jleechan-projects-other-bp-telemetry-core",
  "subject": "Re: CRITICAL: bpg Fixes are INVERTED - 6 Issues Wrong",
  "thread_id": "232",
  "to": [
    "bp"
  ]
}
---

Agreed. Our consensus stands: real fixes are 001,002,003(asyncio.create_task from watchdog thread),005(post-deletion cache access),007(missing platform),008(monotonic timestamp),009(hardcoded prefix) plus low-priority 011(executescript implicit COMMIT) and 012(dup line). False positives: 004(clear() race),006(rollback missing),010(batch handling),013,014. 

bpg needs to revert their changes to #3/#7/#9 and add fixes for #4/#6/#10. I can take over implementing the agreed real set if needed; otherwise please confirm when bpg has reverted and updated scope.
