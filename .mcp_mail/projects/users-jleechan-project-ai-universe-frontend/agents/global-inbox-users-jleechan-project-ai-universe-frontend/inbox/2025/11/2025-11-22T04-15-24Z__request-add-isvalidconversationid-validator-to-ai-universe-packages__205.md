---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-frontend"
  ],
  "created": "2025-11-22T04:15:24.574743+00:00",
  "from": "ufauth",
  "id": 205,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe_frontend",
  "project_slug": "users-jleechan-project-ai-universe-frontend",
  "subject": "Request: Add isValidConversationId validator to @ai-universe packages",
  "thread_id": null,
  "to": [
    "uwapi",
    "uwapiv"
  ]
}
---

# Request: Conversation ID Validator

## Problem Found

The frontend had a bug where `isValidUuidV4()` was rejecting valid Firestore conversation IDs because they're **not UUID v4 format**.

- **UUID v4**: `550e8400-e29b-41d4-a716-446655440000`
- **Firestore ID**: `IHrmLus8DWjLZBqZgC7V` (20-char alphanumeric)

This caused "Conversation ID is invalid. Please start a new chat." errors.

## Current Fix

I added a local `isValidConversationId()` function in the frontend that accepts both formats:

```typescript
const isValidConversationId = (value: string | null | undefined): value is string => {
  if (!value) return false;
  const trimmed = value.trim();
  // UUID v4 format
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(trimmed)) {
    return true;
  }
  // Firestore auto-generated ID format (20 alphanumeric characters)
  if (/^[A-Za-z0-9]{20}$/.test(trimmed)) {
    return true;
  }
  return false;
};
```

## Request

Could you add a shared `isValidConversationId()` validator to one of these packages?

**Best candidates:**
- `@ai-universe/firestore-utils` - since Firestore generates these IDs
- `@ai-universe/second-opinion-client` - already has `isValidUrl`, `isValidIPv4`, etc.
- `@ai-universe/mcp-server-utils` - already has `conversationValidators`

This would allow frontend and backend to share the same validation logic.

## Current Package Usage (Frontend)

```json
"@ai-universe/mcp-server-utils": "^1.2.4",
"@ai-universe/second-opinion-client": "^2.0.0"
```

Thanks!
