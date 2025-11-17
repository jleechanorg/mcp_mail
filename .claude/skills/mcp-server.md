# MCP Agent Mail Server Manager

Manage the MCP Agent Mail HTTP server using local source code.

## Actions

### Start Server

Start the MCP Agent Mail HTTP server in the background using current repository code:

```bash
# Kill any existing server
pkill -f "python.*mcp_agent_mail.*serve-http" || true

# Start server in background with log output
bash -lc "cd \$(git rev-parse --show-toplevel) && ./scripts/run_server_with_token.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"

# Wait for server to start
sleep 2

# Check server status
curl -s http://127.0.0.1:8765/health || echo "Server not responding yet"

# Show log tail
tail -20 /tmp/mcp_agent_mail_server.log
```

### Check Server Status

```bash
# Check if server is running
ps aux | grep -E "python.*mcp_agent_mail.*serve-http" | grep -v grep

# Test HTTP endpoint
curl -s http://127.0.0.1:8765/health | jq '.'

# Check recent logs
tail -50 /tmp/mcp_agent_mail_server.log
```

### Stop Server

```bash
pkill -f "python.*mcp_agent_mail.*serve-http" || true
echo "Server stopped"
```

### Restart Server

```bash
# Stop
pkill -f "python.*mcp_agent_mail.*serve-http" || true
sleep 1

# Start
bash -lc "cd \$(git rev-parse --show-toplevel) && ./scripts/run_server_with_token.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"

# Wait and verify
sleep 2
curl -s http://127.0.0.1:8765/health | jq '.'
```

## Server Details

- **Endpoint:** `http://127.0.0.1:8765/mcp/`
- **Log File:** /tmp/mcp_agent_mail_server.log
- **Script:** ./scripts/run_server_with_token.sh
- **Command:** `uv run python -m mcp_agent_mail.cli serve-http`

## Integration Testing

### Test with Claude Code CLI

```bash
claude --dangerously-skip-permissions -p "Call the MCP tool 'health_check' from mcp-agent-mail server"
```

### Test with Codex CLI

```bash
codex exec --yolo "Call the MCP tool 'health_check' from mcp-agent-mail server"
```

## Troubleshooting

**Server won't start:**
```bash
# Check for port conflicts
lsof -i :8765

# Check logs for errors
cat /tmp/mcp_agent_mail_server.log

# Verify dependencies
cd $(git rev-parse --show-toplevel) && uv sync
```

**Connection errors:**
```bash
# Verify server is listening
curl -v http://127.0.0.1:8765/health

# Check firewall/network
netstat -an | grep 8765
```
