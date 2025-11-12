# Custom Git Hooks (Legacy)

This directory contains custom git hooks that were previously used before adopting the pre-commit framework.

## Current Recommendation

**We now use the [pre-commit framework](https://pre-commit.com/)** which is the Python standard for managing git hooks.

To set up hooks, run:
```bash
./scripts/setup_git_hooks.sh
```

## Legacy Hook

The `pre-commit` script in this directory is kept for reference but is **not actively used**. The pre-commit framework (configured in `.pre-commit-config.yaml`) provides:
- Better hook management and versioning
- Automatic installation and updates
- Multi-language support
- Extensive hook library
- Better caching and performance

## Migration

If you were previously using the custom hook from this directory, please switch to the pre-commit framework by running the setup script above.
