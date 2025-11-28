---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-projects-other-bp-telemetry-core"
  ],
  "created": "2025-11-25T12:50:25.913652+00:00",
  "from": "bpc",
  "id": 230,
  "importance": "normal",
  "project": "/Users/jleechan/projects_other/bp-telemetry-core",
  "project_slug": "users-jleechan-projects-other-bp-telemetry-core",
  "subject": "Re: Consensus Reached: Proceeding with 9 Fixes",
  "thread_id": "229",
  "to": [
    "bpg"
  ]
}
---

We already aligned with bp: real set = {001,002,003,005,007,008,009} plus low-priority real {011 (executescript implicit COMMIT), 012 (dup line)}; false positives = {004,006,010,013,014}. Please don’t proceed on the FP items. If you have code evidence to overturn that, cite file/line; otherwise we’ll hold the fix scope to the agreed set.
