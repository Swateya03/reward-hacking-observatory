"""
Code provenance for a run: which commit the code was at, and whether the tree had
uncommitted changes to tracked files. Recorded once at the start of a run, so every
episode in that run carries the same values.

If git is not available, or the directory is not a repository, both values are None.
A run is never failed for this: the metadata just says it could not be recorded.
"""

import subprocess
from pathlib import Path


def git_provenance(repo_dir: str | Path = ".") -> dict:
    """{"git_commit": "<full sha>" | None, "git_dirty": True | False | None}.

    git_dirty is True when `git status` shows changes to tracked files. Untracked files
    are ignored, so the run's own new output files do not mark the tree dirty."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=10
        )
        if commit.returncode != 0:
            return {"git_commit": None, "git_dirty": None}
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return {"git_commit": commit.stdout.strip(), "git_dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None}
