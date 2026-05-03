from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
from sqlalchemy import desc, select

from mcp_agent_mail.config import get_settings
from mcp_agent_mail.db import ensure_schema, get_session
from mcp_agent_mail.http import build_http_app
from mcp_agent_mail.models import Message


def _slack_signature(secret: str, timestamp: str, body: str) -> str:
    """Compute Slack signature for testing."""
    basestring = f"v0:{timestamp}:{body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    return f"v0={digest}"


@pytest.mark.asyncio
async def test_slack_webhook_creates_message(monkeypatch):
    """Posting to /slack/events should create an MCP message when signature is valid."""
    # Configure Slack env
    monkeypatch.setenv("SLACK_ENABLED", "1")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SLACK_SYNC_ENABLED", "1")
    monkeypatch.setenv("SLACK_SYNC_CHANNELS", "C1234567890")
    monkeypatch.setenv("SLACK_SYNC_PROJECT_NAME", "slack-sync-test")

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()

    app = build_http_app(settings)
    await ensure_schema()

    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "C1234567890",
            "user": "U9999999999",
            "text": "Hello from Slack webhook",
            "ts": "1234567890.123456",
        },
    }
    body = json.dumps(payload)
    timestamp = str(int(time.time()))
    signature = _slack_signature(settings.slack.signing_secret or "", timestamp, body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200

    # Verify message persisted
    async with get_session() as session:
        result = await session.execute(select(Message).order_by(desc(Message.id)).limit(1))
        message = result.scalars().first()

    assert message is not None
    assert "[Slack]" in (message.subject or "")
    assert "Hello from Slack webhook" in (message.body_md or "")


@pytest.mark.asyncio
async def test_slack_webhook_thread_mapping(monkeypatch):
    """Webhook should record thread mapping for Slack thread replies."""
    monkeypatch.setenv("SLACK_ENABLED", "1")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("SLACK_SYNC_ENABLED", "1")
    monkeypatch.setenv("SLACK_SYNC_CHANNELS", "CCHAN123")
    monkeypatch.setenv("SLACK_SYNC_PROJECT_NAME", "slack-sync-test-thread")

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    app = build_http_app(settings)
    await ensure_schema()

    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "CCHAN123",
            "user": "U123",
            "text": "Thread reply content",
            "ts": "2234567890.222222",
            "thread_ts": "1234567890.111111",
        },
    }
    body = json.dumps(payload)
    timestamp = str(int(time.time()))
    signature = _slack_signature(settings.slack.signing_secret or "", timestamp, body)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200

    # Verify message and thread_id stored
    async with get_session() as session:
        result = await session.execute(select(Message).order_by(desc(Message.id)).limit(1))
        message = result.scalars().first()
    assert message is not None
    assert message.thread_id == "slack_CCHAN123_1234567890.111111"
