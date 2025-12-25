import httpx
import pytest
from sqlalchemy import desc, func, select

from mcp_agent_mail.config import get_settings
from mcp_agent_mail.db import ensure_schema, get_session
from mcp_agent_mail.http import build_http_app
from mcp_agent_mail.models import Message


@pytest.mark.asyncio
async def test_slackbox_incoming_creates_message(monkeypatch):
    monkeypatch.setenv("SLACK_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_TOKEN", "slackbox-token")
    monkeypatch.setenv("SLACKBOX_CHANNELS", "CCHAN123")
    monkeypatch.setenv("SLACK_SYNC_PROJECT_NAME", "slackbox-project")

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    app = build_http_app(settings)
    await ensure_schema()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/slackbox/incoming",
                data={
                    "token": "slackbox-token",
                    "channel_id": "CCHAN123",
                    "text": "Slackbox hello world",
                    "timestamp": "1111.2222",
                },
            )

    assert resp.status_code == 200

    async with get_session() as session:
        result = await session.execute(select(Message).order_by(desc(Message.id)).limit(1))
        message = result.scalars().first()

    assert message is not None
    assert settings.slack.slackbox_subject_prefix in (message.subject or "")
    assert message.thread_id == "slackbox_CCHAN123_1111.2222"


@pytest.mark.asyncio
async def test_slackbox_rejects_invalid_token(monkeypatch):
    monkeypatch.setenv("SLACK_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_TOKEN", "expected-token")

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    app = build_http_app(settings)
    await ensure_schema()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/slackbox/incoming",
                data={"token": "wrong", "text": "hi"},
            )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_slackbox_rejects_disallowed_channel(monkeypatch):
    monkeypatch.setenv("SLACK_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_ENABLED", "1")
    monkeypatch.setenv("SLACKBOX_TOKEN", "slackbox-token")
    monkeypatch.setenv("SLACKBOX_CHANNELS", "CCHAN_ALLOWED")

    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    app = build_http_app(settings)
    await ensure_schema()

    async with get_session() as session:
        before_count = (await session.execute(select(func.count(Message.id)))).scalar_one()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/slackbox/incoming",
                data={
                    "token": "slackbox-token",
                    "channel_id": "COTHER",
                    "text": "Slackbox disallowed channel",
                    "timestamp": "2222.3333",
                },
            )

    assert resp.status_code == 200

    async with get_session() as session:
        after_count = (await session.execute(select(func.count(Message.id)))).scalar_one()

    assert after_count == before_count
