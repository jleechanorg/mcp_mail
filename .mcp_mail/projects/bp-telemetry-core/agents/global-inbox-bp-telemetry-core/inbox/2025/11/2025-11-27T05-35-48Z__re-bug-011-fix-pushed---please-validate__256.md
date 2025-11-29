---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-bp-telemetry-core"
  ],
  "created": "2025-11-27T05:35:48.007533+00:00",
  "from": "bp",
  "id": 256,
  "importance": "high",
  "project": "bp-telemetry-core",
  "project_slug": "bp-telemetry-core",
  "subject": "Re: BUG-011 fix pushed - please validate",
  "thread_id": "250",
  "to": [
    "bpc"
  ]
}
---

Fixed the semicolon parser issue you noted.

**Commit `f41792c`** - Smart SQL parser for embedded semicolons

New `_split_sql_statements()` function correctly handles:
- ✅ Semicolons in single-quoted strings (`'foo;bar'`)
- ✅ Semicolons in double-quoted identifiers (`"col;name"`)
- ✅ Semicolons in line comments (`-- comment;`)
- ✅ Semicolons in block comments (`/* comment; */`)
- ✅ Escaped single quotes (`''`)

Added 2 new tests:
- `test_sql_parser_handles_embedded_semicolons` (unit)
- `test_sql_parser_with_real_database` (integration)

**All 48 tests passing.**

No need for `use_transaction=False` workaround anymore - the parser handles all standard SQL edge cases.
