# Running Tests - Complete Test Execution

Execute test suites with proper evidence collection and validation.

## Critical Rules

**NEVER skip tests without explicit user permission.** All tests must be executed unless the user explicitly instructs otherwise.

## Usage

### Run All Tests in testing_llm/

```bash
# Clean database for reproducible results
rm -f .mcp_mail/storage.sqlite3*

# Create master evidence directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
MASTER_DIR="/tmp/testing_llm_evidence_${TIMESTAMP}"
mkdir -p "$MASTER_DIR"
echo "Evidence directory: $MASTER_DIR"

# Run Test 1: MESSAGE_DELIVERY_VALIDATION
python3 scripts/testing/test_message_delivery_validated.py 2>&1 | tee "$MASTER_DIR/test1_message_delivery.log"

# Run Test 2: MULTI_AGENT_MESSAGING_TEST
# (Create test script based on testing_llm/MULTI_AGENT_MESSAGING_TEST.md)
python3 /tmp/test2_multi_agent.py 2>&1 | tee "$MASTER_DIR/test2_multi_agent.log"

# Run Test 3: REAL_CLAUDE_MULTI_AGENT_TEST
# (Create agent prompts and run Claude CLI instances)
# See testing_llm/REAL_CLAUDE_MULTI_AGENT_TEST.md for details

# Generate summary
cat > "$MASTER_DIR/TEST_SUMMARY.md" <<EOF
# Test Execution Summary

Evidence Directory: $MASTER_DIR

## Tests Executed
1. MESSAGE_DELIVERY_VALIDATION - [PASS/FAIL]
2. MULTI_AGENT_MESSAGING_TEST - [PASS/FAIL]
3. REAL_CLAUDE_MULTI_AGENT_TEST - [PASS/FAIL]

## Evidence Files
- test1_message_delivery.log
- test2_multi_agent.log
- test3_real_claude/

## Validation
All tests must pass before claiming validation success.
EOF

echo "All tests complete. Evidence: $MASTER_DIR"
```

### Run Single Test

```bash
# MESSAGE_DELIVERY_VALIDATION
rm -f .mcp_mail/storage.sqlite3*
python3 scripts/testing/test_message_delivery_validated.py

# Check results
cat /tmp/mcp_mail_validation_*/VALIDATION_SUMMARY.txt
```

## Test Descriptions

### Test 1: MESSAGE_DELIVERY_VALIDATION
- **Purpose:** Validate message delivery with SQLite database proof
- **Duration:** ~10 seconds
- **Evidence:** `/tmp/mcp_mail_validation_<timestamp>/`
- **Validates:**
  - Message storage with full content
  - Sender attribution
  - Routing (to/cc/bcc)
  - Content preservation

### Test 2: MULTI_AGENT_MESSAGING_TEST
- **Purpose:** Multi-agent registration and coordination
- **Duration:** ~20 seconds
- **Evidence:** `/tmp/mcp_mail_<branch>_multiagent_<timestamp>/`
- **Validates:**
  - Agent registration
  - Multi-agent messaging
  - Inbox management
  - Message delivery counts

### Test 3: REAL_CLAUDE_MULTI_AGENT_TEST
- **Purpose:** Real Claude CLI instances coordinating via MCP Agent Mail
- **Duration:** 60-120 seconds
- **Evidence:** `/tmp/real_claude_multiagent_<timestamp>/`
- **Validates:**
  - Real-world multi-agent coordination
  - Claude CLI integration
  - Asynchronous message exchange
  - Actual AI agent communication

## Test Execution Policy

When user requests "run all tests" or "run tests in testing_llm/":

1. **List all tests** found in the directory
2. **Check for resource requirements** - If any test requires API credits or external services, ASK user: "Test X requires [resource]. Proceed with all tests?"
3. **Execute ALL tests** unless explicitly instructed to skip
4. **Generate complete evidence** for each test with logs, agent data, messages, and validation results
5. **Provide comprehensive summary** showing pass/fail for each test

### What NOT to Do

- ❌ Skip tests due to assumed cost concerns
- ❌ Execute partial test suites when "all" was requested
- ❌ Decide unilaterally which tests to skip
- ❌ Generate incomplete evidence

### What TO Do

- ✅ Execute every test in the specified suite
- ✅ Ask permission if resources are required
- ✅ Generate complete evidence for all tests
- ✅ Document any skipped tests with explicit user permission
- ✅ Provide clear pass/fail status for each test

## Evidence Requirements

Every test must generate:
- **Execution log** - Complete stdout/stderr from test run
- **Agent data** - Agent profiles and registrations (JSON)
- **Message logs** - All messages sent/received (JSON)
- **Validation results** - Pass/fail with specific criteria checked
- **Summary document** - Human-readable test summary

## Troubleshooting

### Test Failures

If a test fails:
1. Check the execution log for errors
2. Verify MCP Agent Mail server is running
3. Check database state (SQLite)
4. Review test evidence files for details
5. Consult test-specific troubleshooting in testing_llm/

### Database Issues

Clean database for reproducible results:
```bash
rm -f .mcp_mail/storage.sqlite3*
```

### Server Issues

Restart MCP Agent Mail server:
```bash
pkill -f "python.*mcp_agent_mail.*serve-http"
bash -lc "cd $(git rev-parse --show-toplevel) && ./scripts/run_server_with_token.sh >/tmp/mcp_agent_mail_server.log 2>&1 & echo \$!"
sleep 3
curl -s http://127.0.0.1:8765/health | jq '.'
```

## Historical Context

This skill was created after Test 3 (REAL_CLAUDE_MULTI_AGENT_TEST) was initially skipped on 2025-11-18 due to assumed cost concerns. User correctly insisted all tests should run, leading to:
- Immediate execution of Test 3
- Creation of this skill
- Addition of Test Execution Policy to CLAUDE.md
- Update to testing_llm/README.md

**Lesson:** Follow explicit instructions. If user says "run all tests", run ALL tests.
