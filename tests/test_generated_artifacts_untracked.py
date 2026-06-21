from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_generated_static_artifacts_are_not_tracked_by_git():
    result = subprocess.run(
        ["git", "ls-files", "docs/data", "docs/charts"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    tracked = [
        path
        for path in result.stdout.splitlines()
        if not path.endswith("/.gitkeep")
    ]
    assert tracked == []
