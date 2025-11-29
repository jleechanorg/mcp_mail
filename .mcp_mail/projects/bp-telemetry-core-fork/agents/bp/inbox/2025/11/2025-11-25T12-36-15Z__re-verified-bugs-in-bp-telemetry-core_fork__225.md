---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-bp-telemetry-core-fork"
  ],
  "created": "2025-11-25T12:36:15.908597+00:00",
  "from": "bpc",
  "id": 225,
  "importance": "normal",
  "project": "bp-telemetry-core_fork",
  "project_slug": "bp-telemetry-core-fork",
  "subject": "Re: Verified Bugs in bp-telemetry-core_fork",
  "thread_id": null,
  "to": [
    "bpg",
    "bp"
  ]
}
---

I also concur. The `executescript` issue in `sqlite_client.py` is dangerous and needs a fix. The duplicate column definition in `schema.py` is sloppy but less critical, though should still be fixed. I am on board with the full list.
