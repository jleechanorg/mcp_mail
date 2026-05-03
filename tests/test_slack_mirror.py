from __future__ import annotations

from mcp_agent_mail.slack_integration import mirror_message_to_slack


def test_mirror_message_to_slack_posts_when_enabled(monkeypatch):
    captured = {}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return "ok"

    monkeypatch.setenv("SLACK_MCP_MAIL_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setenv("SLACK_MIRROR_ENABLED", "1")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
    monkeypatch.setenv("SLACK_LIVE_TEST", "0")

    monkeypatch.setattr("mcp_agent_mail.slack_integration._post_webhook", fake_post)

    frontmatter = {"project": "proj", "subject": "subj", "thread_id": "tid"}
    body = "hello body"
    resp = mirror_message_to_slack(frontmatter, body)

    assert resp == "ok"
    assert captured["url"] == "https://hooks.slack.com/services/test"
    assert "proj" in captured["payload"]["text"]
    assert "subj" in captured["payload"]["text"]
    assert "tid" in captured["payload"]["text"]
    assert "hello body" in captured["payload"]["text"]


def test_mirror_message_to_slack_skips_when_disabled(monkeypatch):
    monkeypatch.delenv("SLACK_MCP_MAIL_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("SLACK_MIRROR_ENABLED", "0")

    frontmatter = {"project": "proj", "subject": "subj"}
    body = "hello body"
    resp = mirror_message_to_slack(frontmatter, body)

    assert resp is None
