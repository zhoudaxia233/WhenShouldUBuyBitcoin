"""Tests for the main.py pipeline seams (kept light: main() itself is heavy)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

# main.py lives at the repo root, which is not on pytest's pythonpath
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main as m  # noqa: E402


def test_generate_bottom_signals_forwards_strict_flag(monkeypatch):
    # locks the --strict-update wiring: the flag must reach update_onchain_metrics.
    captured = {}

    def fake_update(strict=False):
        captured["strict"] = strict
        raise RuntimeError("stop after capturing strict")

    monkeypatch.setattr(m, "update_onchain_metrics", fake_update)
    empty = pd.DataFrame({"date": [], "close_price": []})

    with pytest.raises(RuntimeError):
        m.generate_bottom_signals(empty, strict_update=True)
    assert captured["strict"] is True

    with pytest.raises(RuntimeError):
        m.generate_bottom_signals(empty, strict_update=False)
    assert captured["strict"] is False


def test_generate_bottom_signals_raises_when_no_data(monkeypatch):
    monkeypatch.setattr(m, "update_onchain_metrics", lambda strict=False: None)
    with pytest.raises(RuntimeError, match="no on-chain data"):
        m.generate_bottom_signals(pd.DataFrame({"date": [], "close_price": []}))
