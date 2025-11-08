# Testing LLM - MCP Agent Mail Test Cases

This directory contains human-readable and LLM-executable test cases for the MCP Agent Mail system. These tests are designed to be read and executed by AI assistants (like Claude) or human testers, not automated test scripts.

## Purpose

The test cases in this directory validate:
- **Agent registration and management**
- **Multi-agent messaging and coordination**
- **Message delivery and inbox functionality**
- **Cross-project communication**
- **System reliability and error handling**

## Test Format

Each test case is a Markdown (`.md`) file with:
- **Test objectives and parameters**
- **Evidence collection setup**
- **Step-by-step instructions**
- **Expected output structure**
- **Validation criteria**
- **Troubleshooting guidance**

## Available Test Cases

### MULTI_AGENT_MESSAGING_TEST.md
**Focus**: Agent registration, messaging, and coordination

**What it tests**:
- Creating 4 agents with different roles (FrontendDev, BackendDev, DatabaseAdmin, DevOpsEngineer)
- Sending messages between agents
- Verifying message delivery via inbox checks
- Saving comprehensive evidence to /tmp

**Expected duration**: 10-30 seconds

**Evidence output**: `/tmp/mcp_agent_mail_<branch>_multiagent_<timestamp>/`

## How to Run Tests as an LLM

### Prerequisites

1. **Ensure MCP Agent Mail is installed**:
   ```bash
   cd /path/to/mcp_agent_mail
   pip install -e .
   ```

2. **Verify installation**:
   ```bash
   python -c "from mcp_agent_mail.app import build_mcp_server; print('✅ MCP Agent Mail installed')"
   ```

3. **Set up your shell** (if using Claude Code or similar):
   ```bash
   # Ensure you're in the project directory
   cd /Users/jleechan/mcp_agent_mail
   ```

### Execution Instructions for LLMs

When an AI assistant (like Claude) is asked to run these tests:

1. **Read the test file completely** - Understand all steps before execution
2. **Set up evidence collection** - Run the bash commands to create TEST_DIR
3. **Execute the Python code** - Run each code block sequentially
4. **Verify success** - Check for ✅ symbols and SUCCESS status
5. **Save evidence** - Confirm all evidence files are created in /tmp
6. **Report results** - Summarize the test outcome to the user

### Example LLM Execution Flow

```markdown
User: "Run the multi-agent messaging test"

LLM Response:
1. Reading MULTI_AGENT_MESSAGING_TEST.md...
2. Setting up evidence collection directory...
3. Executing test steps:
   - Creating project ✅
   - Registering 4 agents ✅
   - Sending 5 messages ✅
   - Verifying delivery ✅
   - Generating evidence ✅
4. Test PASSED - Evidence saved to /tmp/mcp_agent_mail_main_multiagent_20250107_123456/
5. See TEST_SUMMARY.txt for details
```

## Evidence Collection

All tests save evidence to `/tmp` with the following structure:

```
/tmp/mcp_agent_mail_<branch>_<testname>_<timestamp>/
├── TEST_SUMMARY.txt              # Human-readable summary
├── test_info.txt                 # Test metadata
├── evidence/                     # Test result evidence
│   ├── 01_project_creation.json
│   └── FINAL_TEST_RESULTS.json
├── agents/                       # Agent profiles
│   └── *.json
├── messages/                     # Message logs
│   └── all_messages.json
└── inbox/                        # Inbox snapshots
    └── *_inbox.json
```

### Evidence Retention

- Evidence directories include timestamps for uniqueness
- Tests can be run multiple times without conflicts
- Old evidence can be cleaned up with:
  ```bash
  find /tmp -name "mcp_agent_mail_*" -type d -mtime +7 -exec rm -rf {} +
  ```

## Validation

After test execution, verify success by:

1. **Check console output** for ✅ SUCCESS messages
2. **Read TEST_SUMMARY.txt**:
   ```bash
   cat $(ls -t /tmp/mcp_agent_mail_*/TEST_SUMMARY.txt | head -1)
   ```
3. **Verify evidence files**:
   ```bash
   ls -R $(ls -td /tmp/mcp_agent_mail_* | head -1)
   ```
4. **Inspect results**:
   ```bash
   cat $(ls -t /tmp/mcp_agent_mail_*/evidence/FINAL_TEST_RESULTS.json | head -1) | jq .summary
   ```

## Troubleshooting

### Common Issues

#### 1. Import Error
```
ImportError: No module named 'mcp_agent_mail'
```
**Solution**: Install the package: `pip install -e .`

#### 2. Permission Error
```
PermissionError: [Errno 13] Permission denied: '/tmp/...'
```
**Solution**: Check /tmp permissions or use a different directory

#### 3. MCP Server Not Running
```
ConnectionError: Could not connect to MCP server
```
**Solution**: Ensure MCP server is running or use the built-in server

#### 4. Agent Name Conflicts
```
IntegrityError: UNIQUE constraint failed: agents.name
```
**Solution**: Agent names are globally unique - use different names or clean up old agents

### Debug Mode

To run tests with more verbose output:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
# Then run the test code
```

## Creating New Test Cases

To create a new test case:

1. **Copy an existing test file** as a template
2. **Update the test objective** and parameters
3. **Modify the test steps** for your scenario
4. **Update validation criteria** for expected outcomes
5. **Test locally** before committing

### Test Case Template Structure

```markdown
# Test Name: Brief Description
> [!IMPORTANT]
> **Manual LLM Prompt**: ...

## Test Objective
[What this test validates]

## Test Parameters
[Test configuration and expected metrics]

## 📁 Evidence Collection Setup
[Bash commands to set up TEST_DIR]

## Test Instructions
[Step-by-step Python code to execute]

## Expected Output Structure
[Directory structure and file contents]

## Validation Criteria
[Success and failure indicators]

## Troubleshooting
[Common issues and solutions]
```

## Contributing

When adding new test cases:
- Follow the existing markdown format
- Include comprehensive evidence collection
- Provide clear validation criteria
- Add troubleshooting guidance
- Test the test case before committing
- Update this README with the new test

## Best Practices for LLM Testers

1. **Read completely first** - Don't skip ahead
2. **Execute sequentially** - Follow the step order
3. **Verify each step** - Check for ✅ before continuing
4. **Save evidence** - Ensure all files are created
5. **Report clearly** - Summarize results for the user
6. **Clean up responsibly** - Remove test artifacts after verification

## Questions or Issues?

- Check the troubleshooting section in each test case
- Review the main project README at `/Users/jleechan/mcp_agent_mail/README.md`
- Inspect evidence files for debugging clues
- Run tests with DEBUG logging for more details

## License

These test cases are part of the MCP Agent Mail project and follow the same license.
