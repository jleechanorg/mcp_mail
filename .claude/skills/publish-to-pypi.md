# Publishing Python Packages to PyPI

This skill provides step-by-step instructions for publishing Python packages to PyPI.

## Prerequisites

### 1. PyPI Token Configuration

The PyPI token is stored in `~/.bashrc` as an environment variable:

```bash
# Check if token is configured
grep PYPI_TOKEN ~/.bashrc
```

The token should be available in `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-...
```

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
- `dist/<package>-<version>-py3-none-any.whl` (wheel)
- `dist/<package>-<version>.tar.gz` (source distribution)

### Step 5: Test Installation Locally (Optional but Recommended)

```bash
# Create a test virtual environment
python -m venv test_env
source test_env/bin/activate

# Install from local wheel
pip install dist/<package>-<version>-py3-none-any.whl

# Run tests
python -c "import <package>; print(<package>.__version__)"

# Deactivate and remove test env
deactivate
rm -rf test_env
```

### Step 6: Publish to PyPI

```bash
# Source bashrc to ensure credentials are loaded
source ~/.bashrc

# Upload to PyPI
twine upload dist/<package>-<version>-py3-none-any.whl dist/<package>-<version>.tar.gz
```

**Example for mcp_mail:**

```bash
twine upload dist/mcp_mail-0.1.9-py3-none-any.whl dist/mcp_mail-0.1.9.tar.gz
```

### Step 7: Verify Publication

Wait 30-60 seconds for PyPI to update, then:

```bash
# Check PyPI index
pip index versions <package-name>

# Install from PyPI in clean environment
pip install --upgrade <package-name>

# Verify version
python -c "import <package>; print(<package>.__version__)"
```

### Step 8: Test Functionality

Run your test suite to ensure the PyPI package works:

```bash
# For mcp_mail, run the comprehensive test
python testing_llm/test_script.py

# Or run basic functionality test
python -c "from mcp_agent_mail.app import build_mcp_server; print('✅ Works!')"
```

## Common Issues

### Issue: Authentication Error

```
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

```
ERROR HTTPError: 400 Bad Request from https://upload.pypi.org/legacy/
File already exists.
```

**Solution**: You cannot re-upload the same version. Increment version in `pyproject.toml` and rebuild.

### Issue: Python Version Too High

```
ERROR: Could not find a version that satisfies the requirement <package>==X.Y.Z
```

**Solution**: The package requires Python 3.14+ but user has 3.11-3.13. Update `pyproject.toml`:

```toml
requires-python = ">=3.11"  # Change from ">=3.14"
```

Then rebuild and re-publish with a new version number.

### Issue: Package Name Conflicts

```
ERROR HTTPError: 403 Forbidden
The name '<package>' is too similar to an existing project.
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
pip index versions <package-name>
```

## Rollback

If you need to remove a version from PyPI:

**You cannot delete versions** - PyPI doesn't allow deletion to prevent dependency confusion attacks.

Instead:
1. **Yank the version** (makes it unavailable for new installs):
   ```bash
   twine upload --repository pypi --skip-existing --comment "Yanked due to bug" dist/*
   ```

2. **Publish a new fixed version**

3. **Document the issue** in CHANGELOG.md

## Resources

- PyPI Help: https://pypi.org/help/
- Twine Documentation: https://twine.readthedocs.io/
- Python Packaging Guide: https://packaging.python.org/

## Environment Variables

Required environment variables (stored in `~/.bashrc`):

- `PYPI_TOKEN`: Your PyPI API token for authentication
- `GITHUB_TOKEN`: (optional) For automated releases via GitHub Actions

Example `~/.bashrc` entry:

```bash
export PYPI_TOKEN="pypi-AgEI..."
export GITHUB_TOKEN="ghp_..."
```
