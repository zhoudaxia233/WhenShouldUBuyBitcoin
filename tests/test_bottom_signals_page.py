"""Tests for the prerendered bottom-signals dashboard page."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import bottom_signals as bs
from whenshouldubuybitcoin import bottom_signals_page as page


def test_status_for_score_bands():
    assert page._status_for_score(None) == ("No data", "#71717a")
    assert page._status_for_score(17.0)[0] == "Bottom zone"
    assert page._status_for_score(12.0)[0] == "Leaning cheap"
    assert page._status_for_score(7.0)[0] == "Neutral"
    assert page._status_for_score(2.0)[0] == "Rich side"


def test_marker_pct():
    assert page.marker_pct(20.0) == pytest.approx(0.0)
    assert page.marker_pct(0.0) == pytest.approx(100.0)
    assert page.marker_pct(10.0) == pytest.approx(50.0)
    assert page.marker_pct(None) == pytest.approx(50.0)
    assert page.marker_pct(25.0) == pytest.approx(0.0)  # clamped


def test_gauge_svg_contains_needle_and_score():
    svg = page.gauge_svg(55.0, "Watch", "#6e6e73")
    assert svg.startswith("<svg")
    assert ">55<" in svg
    assert svg.count("<path") == 4  # one arc per zone band
    assert "<line" in svg and "<circle" in svg


def test_sparkline_points_shape():
    pts = page.sparkline_points([1.0, 2.0, 3.0, 2.0])
    pairs = [p.split(",") for p in pts.split()]
    assert len(pairs) == 4
    xs = [float(x) for x, _ in pairs]
    assert xs[0] == 0.0 and xs[-1] == pytest.approx(150.0)
    ys = [float(y) for _, y in pairs]
    assert min(ys) >= 0.0 and max(ys) <= 36.0


def test_sparkline_points_handles_flat_and_missing():
    assert page.sparkline_points([]) == ""
    assert page.sparkline_points([5.0]) == ""
    flat = page.sparkline_points([2.0, 2.0, 2.0])
    assert flat  # flat series still renders (mid-height line)
    gappy = page.sparkline_points([1.0, None, 3.0])
    assert len(gappy.split()) == 2
