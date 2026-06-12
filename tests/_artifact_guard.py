"""Pure-logic helper for the real-artifact write guard (test infrastructure).

This module deliberately imports nothing from pytest so its logic can be
unit-tested directly. The companion ``tests/conftest.py`` wires an autouse
fixture around these functions to fail any test that accidentally overwrites a
tracked generated artifact with its production default output path.

The two protected paths are the *defaults* of
``whenshouldubuybitcoin.bottom_signals_page.generate_bottom_signals_page``
(``output_path`` / ``info_path``). Production code (``main.py``) relies on
those defaults to publish the real page, so they must not change; this guard
exists so a future test that forgets to pass ``output_path=`` /``info_path=``
fails loudly instead of silently dirtying the working tree.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# Repo root = .../tests/_artifact_guard.py -> parent.parent.
# Derived from __file__ (NOT cwd) so the guard watches the real tracked files
# regardless of any monkeypatch.chdir(tmp_path) a test may perform.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Absolute paths of the tracked artifacts whose production default output path
# would clobber them. Extend this list to guard more default-output artifacts
# (e.g. docs/data/daily_report.json).
PROTECTED_ARTIFACTS: list[Path] = [
    _REPO_ROOT / "docs" / "charts" / "bottom_signals.html",
    _REPO_ROOT / "docs" / "charts" / "bottom_signals_info.json",
]


def snapshot(paths) -> dict[Path, bytes | None]:
    """Capture each path's exact bytes, or ``None`` if it does not exist.

    Storing the raw bytes (not just a digest) lets ``restore`` rewrite the file
    byte-for-byte. Never raises on a missing file or missing parent directory.
    """
    result: dict[Path, bytes | None] = {}
    for path in paths:
        path = Path(path)
        try:
            result[path] = path.read_bytes()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            result[path] = None
    return result


def _fingerprint(data: bytes | None) -> str | None:
    """sha256 hexdigest of bytes, or ``None`` for a missing file."""
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def diff_snapshots(before: dict, after: dict) -> list[Path]:
    """Return the paths whose content changed (created, modified, or deleted).

    Comparison is by content fingerprint, so a file rewritten with identical
    bytes is correctly reported as unchanged.
    """
    changed: list[Path] = []
    for path, before_data in before.items():
        after_data = after.get(path)
        if _fingerprint(before_data) != _fingerprint(after_data):
            changed.append(path)
    return changed


def restore(before: dict) -> None:
    """Restore each path to its pre-test state, exactly and byte-identically.

    - If the file existed before, rewrite its original bytes (recreating any
      missing parent directory first).
    - If the file did not exist before, delete it (if a test created it).
    """
    for path, before_data in before.items():
        path = Path(path)
        if before_data is None:
            # Did not exist before: remove any file a test created.
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(before_data)
