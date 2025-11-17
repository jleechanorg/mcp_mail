"""Pre-commit guard helpers for MCP Agent Mail."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from .config import Settings
from .storage import ProjectArchive, archive_write_lock, ensure_archive

__all__ = [
    "install_guard",
    "install_prepush_guard",
    "render_precommit_script",
    "render_prepush_script",
    "uninstall_guard",
]


def render_precommit_script(archive: ProjectArchive) -> str:
    """Return the pre-commit script content for the given archive.

    Construct with explicit lines at column 0 to avoid indentation errors.
    """

    file_reservations_dir = str((archive.root / "file_reservations").resolve())
    storage_root = str(archive.root.resolve())
    lines = [
        "#!/usr/bin/env python3",
        "import json",
        "import os",
        "import sys",
        "import subprocess",
        "from pathlib import Path",
        "from fnmatch import fnmatch",
        "from datetime import datetime, timezone",
        "",
        f'FILE_RESERVATIONS_DIR = Path("{file_reservations_dir}")',
        f'STORAGE_ROOT = Path("{storage_root}")',
        'AGENT_NAME = os.environ.get("AGENT_NAME")',
        "if not AGENT_NAME:",
        '    sys.stderr.write("[pre-commit] AGENT_NAME environment variable is required.\\n")',
        "    sys.exit(1)",
        "",
        "if not FILE_RESERVATIONS_DIR.exists():",
        "    sys.exit(0)",
        "",
        "now = datetime.now(timezone.utc)",
        "",
        'staged = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True, check=False)',
        "if staged.returncode != 0:",
        '    sys.stderr.write("[pre-commit] Failed to enumerate staged files.\\n")',
        "    sys.exit(1)",
        "",
        "paths = [line.strip() for line in staged.stdout.splitlines() if line.strip()]",
        "",
        "if not paths:",
        "    sys.exit(0)",
        "",
        "def load_file_reservations():",
        '    for candidate in FILE_RESERVATIONS_DIR.glob("*.json"):',
        "        try:",
        "            data = json.loads(candidate.read_text())",
        "        except Exception:",
        "            continue",
        "        yield data",
        "",
        "conflicts = []",
        "for file_reservation in load_file_reservations():",
        '    if file_reservation.get("agent") == AGENT_NAME:',
        "        continue",
        '    expires = file_reservation.get("expires_ts")',
        "    if expires:",
        "        try:",
        "            expires_dt = datetime.fromisoformat(expires)",
        "            if expires_dt < now:",
        "                continue",
        "        except Exception:",
        "            pass",
        '    pattern = file_reservation.get("path_pattern")',
        "    if not pattern:",
        "        continue",
        "    for path_value in paths:",
        "        if fnmatch(path_value, pattern) or fnmatch(pattern, path_value):",
        '            conflicts.append((path_value, file_reservation.get("agent"), pattern))',
        "",
        "if conflicts:",
        '    sys.stderr.write("[pre-commit] Exclusive file_reservation conflicts detected:\\n")',
        "    for path_value, agent_name, pattern in conflicts:",
        "        sys.stderr.write(f\"  - {path_value} matches file_reservation '{pattern}' held by {agent_name}\\n\")",
        '    sys.stderr.write("Resolve conflicts or release file_reservations before committing.\\n")',
        "    sys.exit(1)",
        "",
        "sys.exit(0)",
    ]
    return "\n".join(lines) + "\n"


def render_prepush_script(archive: ProjectArchive) -> str:
    """Return the pre-push script content that checks conflicts across pushed commits.

    Python script to avoid external shell assumptions; NUL-safe and respects gate/advisory mode.
    """
    file_reservations_dir = str((archive.root / "file_reservations").resolve())
    lines = [
        "#!/usr/bin/env python3",
        "import json",
        "import os",
        "import shutil",
        "import sys",
        "import subprocess",
        "from pathlib import Path",
        "from datetime import datetime, timezone",
        "",
        f'FILE_RESERVATIONS_DIR = Path("{file_reservations_dir}")',
        "",
        "# Ensure uvx (uv tool shim) is available for presubmit checks.",
        "LOCAL_BIN = Path.home() / '.local' / 'bin'",
        "if LOCAL_BIN.is_dir():",
        "    os.environ['PATH'] = f\"{LOCAL_BIN}{os.pathsep}\" + os.environ.get('PATH', '')",
        "UVX = shutil.which('uvx')",
        "if UVX is None:",
        '    sys.stderr.write("[pre-push] uvx executable not found. Install uv and ensure ~/.local/bin is on PATH.\\n")',
        "    sys.exit(1)",
        "",
        "try:",
        '    root_cp = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True)',
        "    REPO_ROOT = Path(root_cp.stdout.strip()) if root_cp.stdout.strip() else Path.cwd()",
        "except Exception:",
        "    REPO_ROOT = Path.cwd()",
        "",
        "PRESUBMIT_COMMANDS = (",
        '    (UVX, "ruff", "check"),',
        '    (UVX, "ty", "check"),',
        ")",
        "for command in PRESUBMIT_COMMANDS:",
        '    display = " ".join(command)',
        '    sys.stdout.write(f"[pre-push] Running {display}\\n")',
        "    result = subprocess.run(command, cwd=REPO_ROOT, env=os.environ.copy(), check=False)",
        "    if result.returncode != 0:",
        '        sys.stderr.write(f"[pre-push] Command failed: {display}\\n")',
        "        sys.exit(result.returncode)",
        "",
        "# Gate",
        'if (os.environ.get("WORKTREES_ENABLED","0") or "0").strip().lower() not in {"1","true","t","yes","y"}:',
        "    sys.exit(0)",
        'MODE = (os.environ.get("AGENT_MAIL_GUARD_MODE","block") or "block").strip().lower()',
        'ADVISORY = MODE in {"warn","advisory","adv"}',
        'AGENT_NAME = os.environ.get("AGENT_NAME")',
        "if not AGENT_NAME:",
        '    sys.stderr.write("[pre-push] AGENT_NAME environment variable is required.\\n")',
        "    sys.exit(1)",
        "if not FILE_RESERVATIONS_DIR.exists():",
        "    sys.exit(0)",
        "",
        "# Read tuples from STDIN: <local ref> <local sha> <remote ref> <remote sha>",
        "tuples = []",
        "for line in sys.stdin.read().splitlines():",
        "    parts = line.strip().split()",
        "    if len(parts) >= 4:",
        "        tuples.append((parts[0], parts[1], parts[2], parts[3]))",
        "",
        "commits = []",
        "for local_ref, local_sha, remote_ref, remote_sha in tuples:",
        "    if not local_sha:",
        "        continue",
        "    # Enumerate commits to be pushed using remote name from args (argv[1]) when available",
        '    remote = (sys.argv[1] if len(sys.argv) > 1 else "origin")',
        "    try:",
        '        cp = subprocess.run(["git","rev-list","--topo-order",local_sha,"--not",f"--remotes={remote}"],',
        "                            check=True,capture_output=True,text=True)",
        "        for sha in cp.stdout.splitlines():",
        "            if sha:",
        "                commits.append(sha.strip())",
        "    except Exception:",
        "        # Fallback: remote range when available",
        '        rng = local_sha if (not remote_sha or set(remote_sha) == {"0"}) else f"{remote_sha}..{local_sha}"',
        "        try:",
        '            cp = subprocess.run(["git","diff","--name-only",rng],check=True,capture_output=True,text=True)',
        "            for p in cp.stdout.splitlines():",
        "                commits.append(p)  # marker; will be handled below",
        "        except Exception:",
        "            pass",
        "",
        "changed = []",
        "for c in commits:",
        "    try:",
        '        cp = subprocess.run(["git","diff-tree","--root","-r","--no-commit-id","--name-only","--no-ext-diff","--diff-filter=ACMRDTU","-z",c],',
        "                            check=True,capture_output=True)",
        '        data = cp.stdout.decode("utf-8","ignore")',
        '        paths = [p for p in data.split("\\x00") if p]',
        "        changed.extend(paths)",
        "    except Exception:",
        "        continue",
        "",
        "def load_file_reservations():",
        '    for candidate in FILE_RESERVATIONS_DIR.glob("*.json"):',
        "        try:",
        "            data = json.loads(candidate.read_text())",
        "        except Exception:",
        "            continue",
        "        yield data",
        "",
        "now = datetime.now(timezone.utc)",
        "conflicts = []",
        "for file_reservation in load_file_reservations():",
        '    if file_reservation.get("agent") == AGENT_NAME:',
        "        continue",
        '    if not file_reservation.get("exclusive", True):',
        "        continue",
        '    expires = file_reservation.get("expires_ts")',
        "    if expires:",
        "        try:",
        "            expires_dt = datetime.fromisoformat(expires)",
        "            if expires_dt < now:",
        "                continue",
        "        except Exception:",
        "            pass",
        '    pattern = (file_reservation.get("path_pattern") or "").strip()',
        "    if not pattern:",
        "        continue",
        "    for path_value in changed:",
        "        # simple fnmatch-style compare; hook remains dependency-free",
        "        import fnmatch as _fn",
        '        a = path_value.replace("\\\\","/").lstrip("/")',
        '        b = pattern.replace("\\\\","/").lstrip("/")',
        "        if _fn.fnmatchcase(a,b) or _fn.fnmatchcase(b,a) or (a==b):",
        '            conflicts.append((path_value, file_reservation.get("agent"), pattern))',
        "",
        "if conflicts:",
        '    sys.stderr.write("[pre-push] Exclusive file_reservation conflicts detected:\\n")',
        "    for path_value, agent_name, pattern in conflicts:",
        "        sys.stderr.write(f\"  - {path_value} matches file_reservation '{pattern}' held by {agent_name}\\n\")",
        "    if ADVISORY:",
        '        sys.stderr.write("[pre-push] Advisory mode: not blocking push (set AGENT_MAIL_GUARD_MODE=block to enforce).\\n")',
        "        sys.exit(0)",
        "    else:",
        '        sys.stderr.write("Resolve conflicts or release file_reservations before pushing.\\n")',
        "        sys.exit(1)",
        "",
        "sys.exit(0)",
    ]
    return "\n".join(lines) + "\n"


async def install_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-commit guard for the given project into the repo."""

    archive = await ensure_archive(settings, project_slug)
    hooks_dir = repo_path / ".git" / "hooks"
    if not hooks_dir.is_dir():
        raise ValueError(f"No git hooks directory at {hooks_dir}")

    hook_path = hooks_dir / "pre-commit"
    script = render_precommit_script(archive)

    async with archive_write_lock(archive):
        await asyncio.to_thread(hooks_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(hook_path.write_text, script, "utf-8")
        await asyncio.to_thread(os.chmod, hook_path, 0o755)
    return hook_path


async def install_prepush_guard(settings: Settings, project_slug: str, repo_path: Path) -> Path:
    """Install the pre-push guard for the given project into the repo."""
    archive = await ensure_archive(settings, project_slug)

    def _git(cwd: Path, *args: str) -> str | None:
        try:
            cp = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
            return cp.stdout.strip()
        except Exception:
            return None

    def _resolve_hooks_dir(repo: Path) -> Path:
        hooks_path = _git(repo, "config", "--get", "core.hooksPath")
        if hooks_path:
            # Check if absolute path: Unix (/foo) or Windows (C:\foo or C:/foo)
            if hooks_path.startswith("/") or (len(hooks_path) > 1 and hooks_path[1] == ":"):
                resolved = Path(hooks_path)
            else:
                root = _git(repo, "rev-parse", "--show-toplevel") or str(repo)
                resolved = Path(root) / hooks_path
            return resolved
        git_dir = _git(repo, "rev-parse", "--git-dir")
        if git_dir:
            g = Path(git_dir)
            if not g.is_absolute():
                g = repo / g
            return g / "hooks"
        return repo / ".git" / "hooks"

    hooks_dir = _resolve_hooks_dir(repo_path)
    await asyncio.to_thread(hooks_dir.mkdir, parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-push"
    script = render_prepush_script(archive)
    async with archive_write_lock(archive):
        await asyncio.to_thread(hook_path.write_text, script, "utf-8")
        await asyncio.to_thread(os.chmod, hook_path, 0o755)
    return hook_path


async def uninstall_guard(repo_path: Path) -> bool:
    """Remove the pre-commit guard from repo, returning True if removed."""

    hook_path = repo_path / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        await asyncio.to_thread(hook_path.unlink)
        return True
    return False
