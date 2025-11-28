---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-ai-universe"
  ],
  "created": "2025-11-21T11:58:57.959304+00:00",
  "from": "uwai",
  "id": 190,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/ai_universe",
  "project_slug": "users-jleechan-project-ai-universe-ai-universe",
  "subject": "Reminder: evidence ready for validation",
  "thread_id": null,
  "to": [
    "uwaiv"
  ]
}
---

Just a reminder: real-mode integration evidence is at `/tmp/ai_universe/local_ratelimit/integration_real/` (summary.json, junit.xml, per-test stdout/stderr, backend.log). All tests passed with CI_SIMULATION=false using run_local_server.sh default rate-limit bypass. PR: https://github.com/jleechanorg/ai_universe/pull/794
