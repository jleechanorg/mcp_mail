# Publishing Python Packages to PyPI

This skill provides step-by-step instructions for publishing Python packages to PyPI.

## Prerequisites

### 1. PyPI Token Configuration

The PyPI token is stored in `~/.bashrc` as an environment variable (for example, `export PYPI_TOKEN="pypi-AgEI..."`). Twine can read `PYPI_TOKEN` directly from the environment, or you can render a `.pypirc` file from that variable before publishing.

```bash
# Check if token is configured
grep PYPI_TOKEN ~/.bashrc
```

To generate `~/.pypirc` **with the actual token value (no variable substitution occurs inside the file itself)**:

```bash
# Render ~/.pypirc from the PYPI_TOKEN in your shell
cat > ~/.pypirc <<EOF
[distutils]
index-servers =
    pypi

[pypi]
username = __token__
password = ${PYPI_TOKEN}
EOF
```

```bash
chmod 600 ~/.pypirc
```

**Security notes:**
- `.pypirc` stores the token in plaintext—restrict access with `chmod 600` and never commit or share this file.
- Keeping `PYPI_TOKEN` in `~/.bashrc` ensures shells and scripts can populate `~/.pypirc` when needed.

### 2. Required Tools

Ensure these tools are installed:

```bash
# Install/upgrade build and publishing tools
pip install --upgrade build twine

# Or with uv
uv pip install --upgrade build twine
```

## Publishing Workflow

### Step 1: Update Version Number

Edit `pyproject.toml` and increment the version:

```toml
[project]
name = "mcp_mail"
version = "0.1.X"  # Increment this
```

**Version bumping guidelines:**
- **Patch (0.1.X)**: Bug fixes, documentation updates
- **Minor (0.X.0)**: New features, backward-compatible changes
- **Major (X.0.0)**: Breaking changes

### Step 2: Update Python Version Requirements

Ensure Python version requirements are realistic:

```toml
requires-python = ">=3.11"  # Use widely available versions, NOT ">=3.14"

classifiers = [
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
]
```

**Important**: Avoid requiring Python 3.14+ as it's still in RC and limits your audience.

### Step 3: Clean Previous Builds

```bash
# Remove old distribution files
rm -rf dist/
rm -rf build/
rm -rf *.egg-info
```

### Step 4: Build the Package

Using `uv` (recommended):

```bash
uv build
```

Using standard `build`:

```bash
python -m build
```

This creates:
- `dist/mcp_mail-<version>-py3-none-any.whl` (wheel)
- `dist/mcp_mail-<version>.tar.gz` (source distribution)

### Step 5: Test Installation Locally (Optional but Recommended)

```bash
# Create a test virtual environment
python -m venv test_env
source test_env/bin/activate

# Install from local wheel
pip install dist/mcp_mail-<version>-py3-none-any.whl

# Run tests
python -c "import mcp_agent_mail; print(mcp_agent_mail.__version__)"

# Deactivate and remove test env
deactivate
rm -rf test_env
```

### Step 6: Publish to PyPI

```bash
# Source bashrc to ensure credentials are loaded
source ~/.bashrc

# Upload to PyPI
twine upload dist/mcp_mail-<version>-py3-none-any.whl dist/mcp_mail-<version>.tar.gz
```

**Example for mcp_mail:**

```bash
twine upload dist/mcp_mail-0.1.9-py3-none-any.whl dist/mcp_mail-0.1.9.tar.gz
```

### Step 7: Verify Publication

Wait 30-60 seconds for PyPI to update, then:

```bash
# Check PyPI index (use the hyphenated project name)
pip index versions mcp-mail

# Install from PyPI in clean environment
pip install --upgrade mcp-mail

# Verify version
python -c "import mcp_agent_mail; print(mcp_agent_mail.__version__)"
```

### Step 8: Test Functionality

Run your test suite to ensure the PyPI package works:

```bash
# For mcp_mail, run the comprehensive test suite
python scripts/testing/test_message_delivery_validated.py

# Or run basic functionality test
python -c "from mcp_agent_mail.app import build_mcp_server; print('✅ Works!')"
```

## Common Issues

### Issue: Authentication Error

```plaintext
ERROR HTTPError: 403 Forbidden from https://upload.pypi.org/legacy/
Invalid or non-existent authentication information.
```

**Solution**: Check that `~/.pypirc` has the correct token:

```bash
# Verify .pypirc exists and has token
cat ~/.pypirc | grep password

# If missing, update it:
# Edit ~/.pypirc and paste the token from ~/.bashrc
```

### Issue: Version Already Exists

```plaintext
ERROR HTTPError: 400 Bad Request from https://upload.pypi.org/legacy/
File already exists.
```

**Solution**: You cannot re-upload the same version. Increment version in `pyproject.toml` and rebuild.

### Issue: Python Version Too Low

```plaintext
ERROR: Could not find a version that satisfies the requirement mcp_mail==X.Y.Z
```

**Solution**: The package requires Python 3.11+ but the environment is older (for example, Python 3.10). Update `pyproject.toml` if needed and rebuild:

```toml
requires-python = ">=3.11"
```

Then rebuild and re-publish with a new version number.

### Issue: Package Name Conflicts

```plaintext
ERROR HTTPError: 403 Forbidden
The name 'mcp_mail' is too similar to an existing project.
```

**Solution**: Choose a different package name or request name release from PyPI.

## Best Practices

### Version Control

Always commit and tag releases:

```bash
# After successful PyPI upload
git add pyproject.toml README.md CHANGELOG.md
git commit -m "Release version X.Y.Z"
git tag -a vX.Y.Z -m "Version X.Y.Z"
git push origin main --tags
```

### Changelog

Maintain a `CHANGELOG.md`:

```markdown
## [0.1.9] - 2025-11-18

### Changed
- Updated Python requirement from >=3.14 to >=3.11 for broader compatibility

### Added
- Credentials management documentation in CLAUDE.md

### Fixed
- README reorganization with install commands at top
```

### Testing Before Release

**Always run tests before publishing:**

1. **Unit tests**: `pytest`
2. **Integration tests**: Run tests from `testing_llm/`
3. **Installation test**: Install from local wheel and verify imports
4. **Functionality test**: Run basic usage scenarios

### Security

- **Never commit** `.pypirc` or `PYPI_TOKEN` to git
- **Rotate tokens** periodically
- **Use scoped tokens** when possible (restrict to specific projects)
- **Store credentials** only in `~/.bashrc` and `~/.pypirc`

## Quick Reference

```bash
# Complete publishing workflow
rm -rf dist/ build/ *.egg-info
uv build
source ~/.bashrc
twine upload dist/*
pip index versions mcp-mail
```

## Rollback

If you need to remove a version from PyPI:

**You cannot delete versions**—PyPI disallows deletion to prevent dependency confusion attacks.

Instead:
1. **Yank the release via PyPI UI or API**:
   - Visit `https://pypi.org/project/mcp-mail/<version>/`
   - Click **Options → Yank this release** and provide a reason
   - Alternatively, use the [warehouse API](https://warehouse.pypa.io/api-reference/legacy/#yank) with `curl` to yank programmatically
2. **Publish a new fixed version**
3. **Document the issue** in `CHANGELOG.md` and notify users in release notes

## Resources

- [PyPI Help](https://pypi.org/help/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [Python Packaging Guide](https://packaging.python.org/)

## Environment Variables

Required environment variables (stored in `~/.bashrc`):

- `PYPI_TOKEN`: Your PyPI API token for authentication
- `GITHUB_TOKEN`: (optional) For automated releases via GitHub Actions

Example `~/.bashrc` entry:

```bash
export PYPI_TOKEN="pypi-AgEI..."
export GITHUB_TOKEN="ghp_..."
```
