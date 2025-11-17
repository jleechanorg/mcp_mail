# Real Claude Multi-Agent Coordination Test
> [!IMPORTANT]
> **This test spawns REAL Claude Code CLI processes** that communicate via MCP Agent Mail

## Test Objective
Validate that multiple Claude Code CLI instances can coordinate through MCP Agent Mail by having real `claude` processes register as agents, send messages, and respond to each other.

## Test Parameters
- **Agent Count**: 3 Claude Code instances
- **Communication Pattern**: Chain messaging (Agent1 → Agent2 → Agent3 → Agent1)
- **Expected Duration**: 60-120 seconds
- **Uses**: Real `claude -p --dangerously-skip-permissions` processes

## Prerequisites
- MCP Agent Mail server running on http://127.0.0.1:8765/mcp/
- `claude` CLI installed and authenticated
- ANTHROPIC_API_KEY commented out (using subscription)

## Test Setup

### 1. Create Evidence Directory
```bash
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TEST_DIR="/tmp/real_claude_multiagent_${TIMESTAMP}"
mkdir -p "$TEST_DIR"/{prompts,outputs,evidence}

echo "TEST_DIR=$TEST_DIR"
echo "Test evidence: $TEST_DIR" | tee "$TEST_DIR/test_info.txt"
```

### 2. Verify MCP Server is Running
```bash
curl -s http://127.0.0.1:8765/health || echo "Start server first!"
ps aux | grep "mcp_agent_mail.*serve-http" | grep -v grep
```

## Test Execution

### Step 1: Agent 1 - Registers and Sends Initial Message

Create prompt file:
```bash
cat > "$TEST_DIR/prompts/agent1_task.txt" <<'EOF'
You are Agent1 (FrontendDev). Your task:

1. Register yourself using the mcp-agent-mail MCP server:
   - Use tool: register_agent
   - project_key: "/tmp/real_claude_test_project"
   - name: "FrontendDev"
   - program: "claude-code"
   - model: "sonnet-4.5"
   - task_description: "React UI Development"

2. Send a message to BackendDev:
   - Use tool: send_message
   - to: ["BackendDev"]
   - subject: "Need API endpoint for dashboard"
   - body_md: "Hi BackendDev! Can you create GET /api/dashboard/stats endpoint? I need it for the React dashboard component."
   - importance: "high"

3. Wait 5 seconds, then check your inbox:
   - Use tool: fetch_inbox
   - limit: 5
   - include_bodies: true

4. Print a summary of:
   - Your agent registration (ID, name)
   - Message sent (to whom, subject)
   - Messages received (count, from whom)

Save all output to demonstrate successful coordination.
EOF
```

Run Agent1:
```bash
claude -p --dangerously-skip-permissions "$(cat $TEST_DIR/prompts/agent1_task.txt)" > "$TEST_DIR/outputs/agent1_output.txt" 2>&1 &
AGENT1_PID=$!
echo "Agent1 (FrontendDev) started - PID: $AGENT1_PID"
```

### Step 2: Agent 2 - Registers, Reads Message, Responds

Create prompt file:
```bash
cat > "$TEST_DIR/prompts/agent2_task.txt" <<'EOF'
You are Agent2 (BackendDev). Your task:

1. Wait 3 seconds for Agent1 to register and send message

2. Register yourself using mcp-agent-mail:
   - project_key: "/tmp/real_claude_test_project"
   - name: "BackendDev"
   - program: "claude-code"
   - model: "sonnet-4.5"
   - task_description: "FastAPI Backend Development"

3. Check your inbox:
   - Use tool: fetch_inbox
   - limit: 5
   - include_bodies: true
   - Look for message from FrontendDev

4. Send message to DatabaseAdmin:
   - to: ["DatabaseAdmin"]
   - subject: "Need help with user stats query"
   - body_md: "Hi DatabaseAdmin! FrontendDev needs dashboard stats. Can you help optimize this query: SELECT * FROM user_activity WHERE date > NOW() - INTERVAL '7 days'?"
   - importance: "normal"

5. Reply to FrontendDev:
   - to: ["FrontendDev"]
   - subject: "Re: Need API endpoint for dashboard"
   - body_md: "Working on it! Asked DatabaseAdmin for help with the query. Will have it ready soon."

6. Print summary showing:
   - Messages received (from FrontendDev)
   - Messages sent (to DatabaseAdmin and FrontendDev)
EOF
```

Run Agent2:
```bash
sleep 2  # Give Agent1 time to start
claude -p --dangerously-skip-permissions "$(cat $TEST_DIR/prompts/agent2_task.txt)" > "$TEST_DIR/outputs/agent2_output.txt" 2>&1 &
AGENT2_PID=$!
echo "Agent2 (BackendDev) started - PID: $AGENT2_PID"
```

### Step 3: Agent 3 - Registers, Reads Message, Completes Chain

Create prompt file:
```bash
cat > "$TEST_DIR/prompts/agent3_task.txt" <<'EOF'
You are Agent3 (DatabaseAdmin). Your task:

1. Wait 6 seconds for other agents to start

2. Register yourself using mcp-agent-mail:
   - project_key: "/tmp/real_claude_test_project"
   - name: "DatabaseAdmin"
   - program: "claude-code"
   - model: "sonnet-4.5"
   - task_description: "PostgreSQL Database Management"

3. Check your inbox:
   - Use tool: fetch_inbox
   - limit: 5
   - include_bodies: true
   - Look for message from BackendDev

4. Send optimized query to BackendDev:
   - to: ["BackendDev"]
   - subject: "Re: Need help with user stats query"
   - body_md: "Here's the optimized query:\\n\\`\\`\\`sql\\nCREATE INDEX IF NOT EXISTS idx_user_activity_date ON user_activity(date);\\nSELECT user_id, COUNT(*) as activity_count FROM user_activity WHERE date > NOW() - INTERVAL '7 days' GROUP BY user_id;\\n\\`\\`\\`\\nThis will be much faster!"
   - importance: "high"

5. Print summary showing:
   - Agent registration
   - Messages received (from BackendDev)
   - Messages sent (to BackendDev)
EOF
```

Run Agent3:
```bash
sleep 4  # Give other agents time to start
claude -p --dangerously-skip-permissions "$(cat $TEST_DIR/prompts/agent3_task.txt)" > "$TEST_DIR/outputs/agent3_output.txt" 2>&1 &
AGENT3_PID=$!
echo "Agent3 (DatabaseAdmin) started - PID: $AGENT3_PID"
```

### Step 4: Wait for Completion

```bash
echo "Waiting for all agents to complete..."
wait $AGENT1_PID
echo "✅ Agent1 completed"
wait $AGENT2_PID
echo "✅ Agent2 completed"
wait $AGENT3_PID
echo "✅ Agent3 completed"
```

### Step 5: Collect Evidence

```bash
echo "Collecting evidence..."

# Save all outputs
cp "$TEST_DIR/outputs"/*.txt "$TEST_DIR/evidence/"

# Create summary
cat > "$TEST_DIR/TEST_SUMMARY.txt" <<EOF
Real Claude Multi-Agent Coordination Test
==========================================

Test Directory: $TEST_DIR
Timestamp: $(date)

Agents Executed:
- Agent1 (FrontendDev): PID $AGENT1_PID
- Agent2 (BackendDev): PID $AGENT2_PID
- Agent3 (DatabaseAdmin): PID $AGENT3_PID

Message Flow:
1. FrontendDev → BackendDev: "Need API endpoint for dashboard"
2. BackendDev → DatabaseAdmin: "Need help with user stats query"
3. BackendDev → FrontendDev: "Working on it! Asked DatabaseAdmin..."
4. DatabaseAdmin → BackendDev: "Here's the optimized query..."

Evidence Files:
$(ls -1 "$TEST_DIR/evidence")

Agent Outputs:
$(ls -1 "$TEST_DIR/outputs")
EOF

cat "$TEST_DIR/TEST_SUMMARY.txt"

echo ""
echo "📁 Evidence saved to: $TEST_DIR"
echo "📄 Agent 1 output: $TEST_DIR/outputs/agent1_output.txt"
echo "📄 Agent 2 output: $TEST_DIR/outputs/agent2_output.txt"
echo "📄 Agent 3 output: $TEST_DIR/outputs/agent3_output.txt"
```

## Expected Results

### Success Indicators
- ✅ All 3 Claude processes start successfully
- ✅ Each agent registers without errors
- ✅ FrontendDev sends message to BackendDev
- ✅ BackendDev receives message from FrontendDev
- ✅ BackendDev sends messages to DatabaseAdmin AND FrontendDev
- ✅ DatabaseAdmin receives message from BackendDev
- ✅ DatabaseAdmin sends optimized query back to BackendDev
- ✅ All agents complete without errors

### Evidence to Verify
1. Check each output file for successful registration
2. Verify messages appear in correct inboxes
3. Confirm no exceptions or MCP errors
4. Validate message chain: Agent1 → Agent2 → Agent3 → Agent2

## Validation

```bash
# Check for successful registrations
grep -i "agent.*registered\|registration.*success" "$TEST_DIR/outputs"/*.txt

# Check for messages sent
grep -i "message.*sent\|sent.*message" "$TEST_DIR/outputs"/*.txt

# Check for messages received
grep -i "inbox\|received.*message" "$TEST_DIR/outputs"/*.txt

# Look for errors
grep -i "error\|exception\|failed" "$TEST_DIR/outputs"/*.txt || echo "✅ No errors found"
```

## Troubleshooting

### Issue: Claude processes hang
**Solution**: Ensure MCP server is running and accessible

### Issue: "Credit balance too low"
**Solution**: Verify ANTHROPIC_API_KEY is commented out in ~/.bashrc

### Issue: Agents can't find each other
**Solution**: All must use same project_key: "/tmp/real_claude_test_project"

### Issue: Message delivery delays
**Solution**: Add sleep delays between agent starts (already included)

## Performance Expectations
- **Agent Registration**: ~2-5 seconds per agent
- **Message Send**: ~1-2 seconds per message
- **Message Receive**: ~1-2 seconds per fetch_inbox
- **Total Test Time**: 60-120 seconds

## Notes
- This test demonstrates REAL multi-agent coordination
- Each Claude instance is independent and autonomous
- Communication happens ONLY through MCP Agent Mail
- This proves the system works for actual agent coordination scenarios

## Cleanup (Optional)

```bash
# Remove test directory after verification
rm -rf "$TEST_DIR"

# Or keep for analysis
echo "Evidence preserved at: $TEST_DIR"
```
