from __future__ import annotations

import time

import httpx
import pytest

from mcp_agent_mail.config import get_settings
from mcp_agent_mail.http import build_http_app


@pytest.mark.asyncio
async def test_slack_and_slackbox_rate_limits_use_independent_config(monkeypatch):
    # Configure per-endpoint limits: Slack limited to 1 req/min, Slackbox to 2 req/min
    monkeypatch.setenv("HTTP_RATE_LIMIT_SLACK_PER_MINUTE", "1")
    monkeypatch.setenv("HTTP_RATE_LIMIT_SLACK_BURST", "1")
    monkeypatch.setenv("HTTP_RATE_LIMIT_SLACKBOX_PER_MINUTE", "2")
    monkeypatch.setenv("HTTP_RATE_LIMIT_SLACKBOX_BURST", "2")

    # Enable Slack + Slackbox endpoints with minimal config so handlers initialize
    monkeypatch.setenv("SLACK_ENABLED", "1")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "dummy-secret")
    monkeypatch.setenv("SLACK_SYNC_ENABLED", "0")
    monkeypatch.setenv("SLACKBOX_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_TOKEN", "slackbox-token")

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    app = build_http_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Slack Events: first request consumes the only token, second should be rate limited
            ts = str(int(time.time()))
            resp1 = await client.post(
                "/slack/events",
                content="{}",
                headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=invalid"},
            )
            assert resp1.status_code != 429

            resp2 = await client.post(
                "/slack/events",
                content="{}",
                headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": "v0=invalid"},
            )
            assert resp2.status_code == 429

            # Slackbox: burst of two should be allowed, third should be limited
            form = {
                "token": "slackbox-token",
                "text": "hello from slackbox",
                "channel_name": "CCHAN123",
                "timestamp": "1111.2222",
            }
            resp3 = await client.post("/slackbox/incoming", data=form)
            resp4 = await client.post("/slackbox/incoming", data=form)

            assert resp3.status_code != 429
            assert resp4.status_code != 429

            resp5 = await client.post("/slackbox/incoming", data=form)
            assert resp5.status_code == 429
