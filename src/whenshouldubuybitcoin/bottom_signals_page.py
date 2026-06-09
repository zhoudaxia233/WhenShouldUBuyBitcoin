"""
Prerendered on-chain bottom-signals dashboard (Jinja2).

All values, the gauge SVG, sparklines, and backtest JSON are computed here
and embedded into a self-contained static page; the only client-side JS is
the threshold/duration toggle for the main chart.
"""

import json
import math
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from .bottom_signals import ZONE_ADVICE, zone_for

TEMPLATE_DIR = Path(__file__).parent / "templates"
PLOTLY_CDN = "https://cdn.plot.ly/plotly-3.2.0.min.js"

OUTPUT_HTML = Path("docs/charts/bottom_signals.html")
OUTPUT_INFO = Path("docs/charts/bottom_signals_info.json")


def _status_for_score(score) -> tuple[str, str]:
    """Uniform per-signal status label/color from the 0-20 score."""
    if score is None or pd.isna(score):
        return "No data", "#71717a"
    if score >= 15:
        return "Bottom zone", "#3b82f6"
    if score >= 10:
        return "Leaning cheap", "#10b981"
    if score >= 5:
        return "Neutral", "#d97706"
    return "Rich side", "#6e6e73"


def marker_pct(score) -> float:
    """Marker position on the 4-band score bar; left edge = bottom (score 20)."""
    if score is None or pd.isna(score):
        return 50.0
    return max(0.0, min(100.0, 100.0 - 5.0 * float(score)))


def _polar(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def _arc_path(cx, cy, r, start_deg, end_deg) -> str:
    x1, y1 = _polar(cx, cy, r, start_deg)
    x2, y2 = _polar(cx, cy, r, end_deg)
    large = 1 if (start_deg - end_deg) > 180 else 0
    return f"M {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f}"


def gauge_svg(score: float, zone_label: str, zone_color: str) -> str:
    """Semi-circular 0-100 gauge; 0 at the left (180 deg), 100 at the right."""
    cx, cy, r = 170.0, 165.0, 118.0

    def angle(v: float) -> float:
        return 180.0 - 1.8 * v

    zone_bands = [
        (0, 60, "#d2d2d7"),
        (60, 70, "#10b981"),
        (70, 80, "#f59e0b"),
        (80, 100, "#ef4444"),
    ]
    arcs = "".join(
        f'<path d="{_arc_path(cx, cy, r, angle(lo), angle(hi))}" fill="none" '
        f'stroke="{color}" stroke-width="28"/>'
        for lo, hi, color in zone_bands
    )
    ticks = "".join(
        f'<text x="{x:.1f}" y="{y:.1f}" fill="#86868b" font-size="10" '
        f'text-anchor="middle" dominant-baseline="middle">{v}</text>'
        for v in (0, 60, 70, 80, 100)
        for x, y in [_polar(cx, cy, r + 24, angle(v))]
    )
    clamped = max(0.0, min(100.0, float(score)))
    nx, ny = _polar(cx, cy, r - 40, angle(clamped))
    needle = (
        f'<line x1="{cx}" y1="{cy}" x2="{nx:.2f}" y2="{ny:.2f}" '
        f'stroke="{zone_color}" stroke-width="3" stroke-linecap="round"/>'
        f'<circle cx="{cx}" cy="{cy}" r="6" fill="{zone_color}"/>'
    )
    label = (
        f'<text x="{cx}" y="127" fill="{zone_color}" font-size="46" '
        f'font-weight="700" text-anchor="middle">{score:.0f}</text>'
        f'<text x="{cx}" y="151" fill="#86868b" font-size="13" '
        f'text-anchor="middle">/ 100</text>'
    )
    return (
        '<svg viewBox="-10 0 360 200" width="100%" '
        'style="max-width:380px;display:block;">'
        + arcs + ticks + needle + label + "</svg>"
    )


def sparkline_points(values, width: float = 150.0, height: float = 36.0) -> str:
    """SVG polyline points for a score sparkline; skips missing values."""
    clean = [None if (v is None or pd.isna(v)) else float(v) for v in (values or [])]
    present = [v for v in clean if v is not None]
    if len(present) < 2:
        return ""
    vmin, vmax = min(present), max(present)
    span = (vmax - vmin) or 1.0
    n = len(clean)
    pts = []
    for i, v in enumerate(clean):
        if v is None:
            continue
        x = width * i / (n - 1)
        y = 2.0 + (height - 4.0) * (1.0 - (v - vmin) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)
