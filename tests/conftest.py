"""Shared fixtures for the top-level ``tests/`` suite.

Scope note: this conftest applies to ``tests/`` and below only, NOT to
``dca_service/tests/`` (which has its own conftest). That is the intended
scope for the artifact guard below.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# conftest.py is loaded at the rootdir before pytest's import mode adds this
# directory to sys.path, so make the sibling helper importable explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _artifact_guard import (  # noqa: E402  (import after sys.path tweak)
    PROTECTED_ARTIFACTS,
    diff_snapshots,
    restore,
    snapshot,
)


@pytest.fixture(autouse=True)
def _guard_real_artifacts():
    """Fail any test that writes a tracked generated artifact in place.

    Several page generators default ``output_path`` / ``info_path`` to the real
    tracked file under ``docs/charts/``. Tests are expected to redirect those
    into ``tmp_path``; a test that forgets would silently overwrite the tracked
    artifact and dirty the working tree. This autouse guard snapshots those
    files before each test and, if any changed afterward, restores the originals
    first (so the tree stays clean even on failure) and then fails the test.
    """
    before = snapshot(PROTECTED_ARTIFACTS)
    yield
    after = snapshot(PROTECTED_ARTIFACTS)
    changed = diff_snapshots(before, after)
    if changed:
        # Restore BEFORE failing so the working tree is never left dirty.
        restore(before)
        names = "\n  - ".join(str(p) for p in changed)
        pytest.fail(
            "Test wrote real generated artifact(s) in place:\n  - "
            + names
            + "\nPass output_path=/info_path= pointing into tmp_path so the test "
            "does not clobber the tracked file. (Originals have been restored.)",
            pytrace=False,
        )
