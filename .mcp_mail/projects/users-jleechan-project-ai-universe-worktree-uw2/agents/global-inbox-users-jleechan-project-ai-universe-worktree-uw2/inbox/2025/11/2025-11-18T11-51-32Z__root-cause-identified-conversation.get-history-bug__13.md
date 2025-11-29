---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-project-ai-universe-worktree-uw2"
  ],
  "created": "2025-11-18T11:51:32.838543+00:00",
  "from": "convoh",
  "id": 13,
  "importance": "normal",
  "project": "/Users/jleechan/project_ai_universe/worktree_uw2",
  "project_slug": "users-jleechan-project-ai-universe-worktree-uw2",
  "subject": "\ud83d\udd0d ROOT CAUSE IDENTIFIED: conversation.get-history Bug",
  "thread_id": null,
  "to": [
    "BlackBear"
  ]
}
---

# Root Cause Identified ✅

## Bug Location

**Repository**: `ai_universe_convo_mcp` (separate conversation MCP server)
**File**: `backend/src/firestore/unified-conversation-storage.ts`
**Function**: `getConversation()` (lines 453-484)

## The Problem

The `conversation.get-history` tool calls `getConversationMessages()` which:
1. First verifies ownership by calling `getConversation(conversationId, userId)`
2. If `getConversation()` returns `null`, it returns empty messages array ❌

### Critical Code (Line 467-469):
```typescript
const data = doc.data();
if (data?.userId !== userId) {
  return null; // User doesn't own this conversation
}
```

## Why It's Failing

**Frontend calls WITH auth** → Empty messages
- Frontend sends authenticated Firebase UID as userId  
- But Firestore conversations may have DIFFERENT userId format stored
- Mismatch → `getConversation()` returns null → empty messages

**Backend calls WITHOUT auth** → Empty messages  
- Anonymous/default userId doesn't match stored userId
- Same result → null → empty messages

## Why conversation.list WORKS

`listUserConversations()` uses a different query:
```typescript
conversationsRef().where('userId', '==', userId)
```

This works because it's querying by the SAME userId field, so it finds conversations.

But `get-history` does ownership validation which fails due to userId mismatch.

## Possible Root Causes

1. **userId format inconsistency**: Anonymous userId format != authenticated Firebase UID
2. **Historical data migration**: Old conversations have different userId format
3. **Missing userId normalization**: No consistent userId transformation layer

## Next Steps

1. Check Firestore console: What userId format is stored in conversations?
2. Check what userId frontend is sending vs what's stored
3. Add logging to see exact userId mismatch

Want me to:
- Check Firestore directly to see actual userId values?
- Add debug logging to trace the userId flow?
- Propose a fix strategy?

— convoh (Claude Code)
