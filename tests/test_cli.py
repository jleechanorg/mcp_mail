import asyncio
from typing import Any

from typer.testing import CliRunner

from mcp_agent_mail.cli import app
from mcp_agent_mail.db import ensure_schema, get_session
from mcp_agent_mail.models import Agent, Project


def test_cli_lint(monkeypatch):
    runner = CliRunner()
    captured: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        captured.append(command)

    monkeypatch.setattr("mcp_agent_mail.cli._run_command", fake_run)
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0
    assert captured == [["ruff", "check", "--fix", "--unsafe-fixes"]]


def test_cli_typecheck(monkeypatch):
    runner = CliRunner()
    captured: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        captured.append(command)

    monkeypatch.setattr("mcp_agent_mail.cli._run_command", fake_run)
    result = runner.invoke(app, ["typecheck"])
    assert result.exit_code == 0
    assert captured == [["uvx", "ty", "check"]]


def test_cli_serve_http_uses_settings(isolated_env, monkeypatch):
    runner = CliRunner()
    call_args: dict[str, Any] = {}

    def fake_uvicorn_run(app, host, port, log_level="info"):
        call_args["app"] = app
        call_args["host"] = host
        call_args["port"] = port
        call_args["log_level"] = log_level

    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)
    result = runner.invoke(app, ["serve-http"])
    assert result.exit_code == 0
    assert call_args["host"] == "127.0.0.1"
    assert call_args["port"] == 8765


def test_cli_migrate(monkeypatch):
    runner = CliRunner()
    invoked: dict[str, bool] = {"called": False}

    async def fake_migrate(settings):
        invoked["called"] = True

    monkeypatch.setattr("mcp_agent_mail.cli.ensure_schema", fake_migrate)
    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0
    assert invoked["called"] is True


def test_cli_list_projects(isolated_env):
    runner = CliRunner()

    async def seed() -> None:
        await ensure_schema()
        async with get_session() as session:
            project = Project(slug="demo", human_key="Demo")
            session.add(project)
            await session.commit()
            await session.refresh(project)
            session.add(
                Agent(
                    project_id=project.id,
                    name="BlueLake",
                    program="codex",
                    model="gpt-5",
                    task_description="",
                )
            )
            await session.commit()

    asyncio.run(seed())
    result = runner.invoke(app, ["list-projects", "--include-agents"])
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "BlueLake" not in result.stdout


def test_cli_serve_http_rejects_python_314(monkeypatch):
    """Test that serve-http exits with error on Python 3.14+."""
    runner = CliRunner()

    # Mock sys.version_info to simulate Python 3.14
    original_version_info = sys.version_info

    class FakeVersionInfo:
        major = 3
        minor = 14
        micro = 0

        def __ge__(self, other):
            if isinstance(other, tuple):
                return (self.major, self.minor) >= other
            return NotImplemented

    monkeypatch.setattr("mcp_agent_mail.cli.sys.version_info", FakeVersionInfo())

    result = runner.invoke(app, ["serve-http"])
    assert result.exit_code == 1
    assert "Python 3.14+ is not supported" in result.stdout
    assert "beartype" in result.stdout
    assert "python3.13" in result.stdout or "python3.12" in result.stdout or "python3.11" in result.stdout
