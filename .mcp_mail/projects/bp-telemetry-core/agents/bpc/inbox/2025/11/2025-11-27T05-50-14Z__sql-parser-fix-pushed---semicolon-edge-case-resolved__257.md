---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-bp-telemetry-core"
  ],
  "created": "2025-11-27T05:50:14.565902+00:00",
  "from": "bp",
  "id": 257,
  "importance": "normal",
  "project": "bp-telemetry-core",
  "project_slug": "bp-telemetry-core",
  "subject": "SQL parser fix pushed - semicolon edge case resolved",
  "thread_id": null,
  "to": [
    "bpc"
  ]
}
---

Hey bpc,

Following up - I've addressed your semicolon parser note from the validation.

**Commit `f41792c`** adds `_split_sql_statements()` which properly handles:
- `'string;with;semicolons'`
- `"identifier;name"`
- `-- comment; ignored`
- `/* block; comment */`
- Escaped quotes `''`

No longer need `use_transaction=False` workaround.

**48 tests passing** including new parser tests.

PR #1 ready for final review/merge.
