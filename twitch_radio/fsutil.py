"""Owner-only permissions for the files this bot keeps (database, backups,
logs, state directories). Best effort: on a filesystem that doesn't support
modes (some mounts, Windows) it quietly does nothing."""

from __future__ import annotations

import contextlib
from pathlib import Path

PRIVATE_FILE = 0o600
PRIVATE_DIR = 0o700


def make_private(path: Path, mode: int = PRIVATE_FILE) -> None:
    with contextlib.suppress(OSError):
        path.chmod(mode)


def private_dir(path: Path) -> None:
    """Creates `path` if needed and restricts it to the owner."""
    path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR)
    make_private(path, PRIVATE_DIR)
