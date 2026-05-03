# Slackbox Support Design

## Goal
Provide a minimal, webhook-only path for importing Slack channel chatter into MCP Agent Mail when a full Slack bot app is unavailable. Slackbox relies on Slack's legacy **Outgoing Webhooks/Slash Command style payloads** so users can forward channel posts to MCP mail with only a verification token and channel allowlist.

## Requirements
- **No bot token required:** Works even when `SLACK_BOT_TOKEN` is absent.
- **Webhook verification:** Reject requests without the configured Slackbox token.
- **Channel scoping:** Only ingest messages from allowed channels/IDs.
- **Thread grouping:** Derive stable `thread_id` using channel + timestamp when provided.
- **Subject hygiene:** Prefix subjects to differentiate Slackbox traffic and trim to MCP limits.
- **Deduplication:** Reuse existing in-memory Slack event cache to drop duplicates from retries.
- **Operational ergonomics:** Reuse the Slack sync project and synthetic `Slackbox` agent so inbox flows and archives match the existing Slack bridge.

## Data Flow
1. Slack posts an `application/x-www-form-urlencoded` payload (token, channel, user, text, timestamp) to `/slackbox/incoming`.
2. The server verifies the token, checks allowed channels, and normalizes the text into an MCP message envelope:
   - Sender: `Slackbox` (configurable)
   - Subject: `[Slackbox] <first line>` (prefix configurable)
   - Body: raw text with Slack mentions untouched
   - Thread: `slackbox_<channel>_<timestamp>` when both are available
3. The payload is ingested via the shared Slack bridge path, but Slackbox messages use a separate, configurable sender agent name (from `SLACKBOX_SENDER_NAME`, default "Slackbox") rather than "SlackBridge". The message is broadcast to all active agents in the Slack sync project, written to the archive, and dedupe keys are recorded.

## Configuration
New environment flags (read via `SlackSettings`):

- `SLACKBOX_ENABLED` (default `false`): turn Slackbox ingestion on.
- `SLACKBOX_TOKEN`: verification token from the Slack outgoing webhook/slash command.
- `SLACKBOX_CHANNELS`: comma-separated list of allowed channel IDs or names; empty means allow all.
- `SLACKBOX_SENDER_NAME` (default `Slackbox`): synthetic agent name for ingested messages.
- `SLACKBOX_SUBJECT_PREFIX` (default `[Slackbox]`): prepended to created subjects.

Slackbox reuses `SLACK_SYNC_PROJECT_NAME` to choose the project that receives the messages.

## Error Handling & Limits
- 401 for invalid token.
- 403 when Slackbox is disabled or the Slackbox token is not configured (the Slack signing secret is not used for this endpoint).
- Empty texts short-circuit with a friendly 200 response to avoid noisy retries.
- Dedupe cache prevents duplicate inserts on webhook retries using `(channel, timestamp)` keys when available.

## Testing Strategy
- Unit/integration tests for `/slackbox/incoming`:
  - Token acceptance/rejection.
  - Happy path creates a message with expected subject/prefix and thread grouping.
  - Disallowed channel short-circuits without creating a message.
