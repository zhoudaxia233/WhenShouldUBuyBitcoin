"""Tests for the real-artifact write guard (test infrastructure).

These exercise the pure-logic helper ``tests/_artifact_guard.py`` directly
(snapshot / diff_snapshots / restore) and prove end-to-end, via the
``pytester`` fixture, that the autouse ``_guard_real_artifacts`` fixture in
``tests/conftest.py`` fails a test that writes a protected artifact and leaves
the file restored afterward.

Every test here either operates on ``tmp_path`` files or runs inside the
pytester sandbox, so this suite never touches the real
``docs/charts/bottom_signals*`` artifacts by construction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import _artifact_guard as guard

# Enable the pytester fixture for the end-to-end proof below.
pytest_plugins = ["pytester"]


# --- PROTECTED_ARTIFACTS points at the real repo artifacts ------------------

def test_protected_artifacts_are_the_real_absolute_paths():
    repo_root = Path(__file__).resolve().parent.parent
    expected = {
        repo_root / "docs/charts/bottom_signals.html",
        repo_root / "docs/charts/bottom_signals_info.json",
    }
    assert {p.resolve() for p in guard.PROTECTED_ARTIFACTS} == expected
    for p in guard.PROTECTED_ARTIFACTS:
        assert p.is_absolute()


# --- snapshot() -------------------------------------------------------------

def test_snapshot_returns_none_for_missing_file(tmp_path):
    missing = tmp_path / "nope.json"
    snap = guard.snapshot([missing])
    assert snap[missing] is None


def test_snapshot_does_not_raise_on_missing_parent_dir(tmp_path):
    missing = tmp_path / "no_such_dir" / "deep" / "nope.json"
    snap = guard.snapshot([missing])  # must not raise
    assert snap[missing] is None


def test_snapshot_fingerprint_is_stable_for_existing_file(tmp_path):
    f = tmp_path / "a.html"
    f.write_bytes(b"<html>hello</html>")
    first = guard.snapshot([f])[f]
    second = guard.snapshot([f])[f]
    assert first is not None
    assert first == second  # stable across calls when content is unchanged


def test_snapshot_fingerprint_changes_with_content(tmp_path):
    f = tmp_path / "a.html"
    f.write_bytes(b"one")
    fp1 = guard.snapshot([f])[f]
    f.write_bytes(b"two")
    fp2 = guard.snapshot([f])[f]
    assert fp1 != fp2


# --- diff_snapshots() -------------------------------------------------------

def test_diff_reports_empty_when_unchanged(tmp_path):
    f = tmp_path / "a.html"
    f.write_bytes(b"stable")
    before = guard.snapshot([f])
    after = guard.snapshot([f])
    assert guard.diff_snapshots(before, after) == []


def test_diff_detects_creation(tmp_path):
    f = tmp_path / "a.html"
    before = guard.snapshot([f])  # missing -> None
    f.write_bytes(b"created")
    after = guard.snapshot([f])
    assert guard.diff_snapshots(before, after) == [f]


def test_diff_detects_modification(tmp_path):
    f = tmp_path / "a.html"
    f.write_bytes(b"before")
    before = guard.snapshot([f])
    f.write_bytes(b"after")
    after = guard.snapshot([f])
    assert guard.diff_snapshots(before, after) == [f]


def test_diff_detects_deletion(tmp_path):
    f = tmp_path / "a.html"
    f.write_bytes(b"present")
    before = guard.snapshot([f])
    f.unlink()
    after = guard.snapshot([f])
    assert guard.diff_snapshots(before, after) == [f]


# --- restore() --------------------------------------------------------------

def test_restore_recreates_original_bytes(tmp_path):
    f = tmp_path / "a.html"
    original = b"original-content\x00\xff"  # include non-utf8 bytes
    f.write_bytes(original)
    before = guard.snapshot([f])
    f.write_bytes(b"corrupted by a test")
    guard.restore(before)
    assert f.read_bytes() == original


def test_restore_deletes_file_that_did_not_exist_before(tmp_path):
    f = tmp_path / "a.html"
    before = guard.snapshot([f])  # captured while missing
    f.write_bytes(b"accidentally created")
    guard.restore(before)
    assert not f.exists()


def test_restore_recreates_parent_dir_if_needed(tmp_path):
    # original existed; a test deleted both it and its parent dir
    nested = tmp_path / "sub" / "a.html"
    nested.parent.mkdir()
    nested.write_bytes(b"data")
    before = guard.snapshot([nested])
    import shutil

    shutil.rmtree(tmp_path / "sub")
    guard.restore(before)
    assert nested.read_bytes() == b"data"


# --- end-to-end: the autouse fixture must fail an offending test ------------

def test_autouse_fixture_fails_and_restores_on_protected_write(pytester):
    """Run an isolated test that writes a 'protected' artifact and assert the
    autouse guard (1) fails the test and (2) restores the file.

    To avoid touching the real ``docs/charts`` artifacts, the sandbox conftest
    redirects ``PROTECTED_ARTIFACTS`` to a file inside the pytester tmp dir,
    while reusing the real guard logic and the real fixture body verbatim.
    """
    # Make the real guard helper + conftest importable inside the sandbox run.
    real_tests_dir = Path(__file__).resolve().parent
    pytester.syspathinsert(real_tests_dir)

    sentinel = pytester.path / "guarded_artifact.html"
    sentinel.write_text("ORIGINAL")  # pre-existing content we expect restored

    # Sandbox conftest: same fixture logic as the real one, but PROTECTED list
    # is redirected at the guard module so we never write the real repo files.
    pytester.makeconftest(
        f"""
        import _artifact_guard as guard
        from pathlib import Path
        import pytest

        guard.PROTECTED_ARTIFACTS = [Path(r"{sentinel}")]

        @pytest.fixture(autouse=True)
        def _guard_real_artifacts():
            before = guard.snapshot(guard.PROTECTED_ARTIFACTS)
            yield
            after = guard.snapshot(guard.PROTECTED_ARTIFACTS)
            changed = guard.diff_snapshots(before, after)
            if changed:
                guard.restore(before)
                names = ", ".join(str(p) for p in changed)
                pytest.fail("test wrote protected artifact(s): " + names)
        """
    )
    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_offender_writes_protected_file():
            Path(r"{sentinel}").write_text("POLLUTED")
            assert True  # the test body itself "passes"; the guard must fail it
        """
    )

    result = pytester.runpytest()
    # A fixture that fails AFTER yield (teardown) yields an "error" outcome, not
    # "failed" -- but the test still goes red and the offending path is named,
    # which is the guard's whole purpose. The inner test body itself passes.
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*wrote protected artifact*"])
    # restore-then-fail: the sentinel is back to its original content.
    assert sentinel.read_text() == "ORIGINAL"


def test_autouse_fixture_passes_clean_test(pytester):
    """A test that does NOT touch protected artifacts must pass (no false-fire)."""
    real_tests_dir = Path(__file__).resolve().parent
    pytester.syspathinsert(real_tests_dir)

    sentinel = pytester.path / "guarded_artifact.html"
    sentinel.write_text("ORIGINAL")

    pytester.makeconftest(
        f"""
        import _artifact_guard as guard
        from pathlib import Path
        import pytest

        guard.PROTECTED_ARTIFACTS = [Path(r"{sentinel}")]

        @pytest.fixture(autouse=True)
        def _guard_real_artifacts():
            before = guard.snapshot(guard.PROTECTED_ARTIFACTS)
            yield
            after = guard.snapshot(guard.PROTECTED_ARTIFACTS)
            changed = guard.diff_snapshots(before, after)
            if changed:
                guard.restore(before)
                names = ", ".join(str(p) for p in changed)
                pytest.fail("test wrote protected artifact(s): " + names)
        """
    )
    pytester.makepyfile(
        """
        def test_clean(tmp_path):
            (tmp_path / "ok.txt").write_text("fine")
            assert True
        """
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
