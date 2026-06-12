"""
Prerendered on-chain bottom-signals dashboard (Jinja2).

All values, the gauge SVG, sparklines, and backtest JSON are computed here
and embedded into a self-contained static page; the only client-side JS is
the threshold/duration toggle for the main chart.
"""

import json
import math
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from .bottom_signals import CYCLE_BOTTOMS, DURATIONS, THRESHOLDS, ZONE_ADVICE, zone_for
from .persistence import _atomic_write_text

TEMPLATE_DIR = Path(__file__).parent / "templates"
PLOTLY_CDN = "https://cdn.plot.ly/plotly-3.2.0.min.js"

OUTPUT_HTML = Path("docs/charts/bottom_signals.html")
OUTPUT_INFO = Path("docs/charts/bottom_signals_info.json")


def _json_for_script(obj) -> str:
    """json.dumps escaped so the payload cannot break out of a <script> block.

    Escaping ``<``/``>``/``&`` neutralises a ``</script>`` injection, and the
    U+2028/U+2029 line separators are escaped because they are illegal raw in JS
    string literals. For ordinary data (dates, numbers) the output is identical
    to plain json.dumps, so the rendered page is unchanged.
    """
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


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


SIGNAL_DEFS = [
    ("s1", "S1 · Holder Cost Basis", "Price vs the three holder cost-basis lines"),
    ("s2", "S2 · MVRV Deviation", "Market value vs aggregate on-chain cost basis"),
    ("s3", "S3 · Supply in Loss", "Share of supply underwater (more = closer to a bottom)"),
    ("s4", "S4 · Capital Net Change", "30-day realized-cap inflow / outflow"),
    ("s5", "S5 · Fear & Greed", "How cold is market sentiment"),
]

SIGNAL_SHORT_LABELS = {
    "s1": "Holder cost",
    "s2": "MVRV",
    "s3": "Supply in loss",
    "s4": "Capital flow",
    "s5": "Fear & Greed",
}


def _fmt_usd_compact(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    sign = "-" if value < 0 else "+"
    v = abs(float(value))
    if v >= 1e12:
        return f"{sign}${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.0f}M"
    return f"{sign}${v:,.0f}"


def _fng_classification(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    v = float(value)
    if v <= 25:
        return "Extreme Fear"
    if v <= 45:
        return "Fear"
    if v < 55:
        return "Neutral"
    if v < 75:
        return "Greed"
    return "Extreme Greed"


def _rel_line(price: float, line) -> str:
    if line is None or pd.isna(line) or line <= 0:
        return "N/A"
    pct = (price / float(line) - 1.0) * 100.0
    side = "above" if pct >= 0 else "below"
    return f"price {abs(pct):.1f}% {side}"


def _build_cards(latest: pd.Series, scores_df: pd.DataFrame) -> list[dict]:
    cards = []
    spark_window = scores_df.tail(90)
    for key, title, subtitle in SIGNAL_DEFS:
        score = latest.get(key)
        status, color = _status_for_score(score)
        score_missing = score is None or pd.isna(score)
        price = float(latest["close_price"])

        if key == "s1":
            now_html = f"Current BTC <b>${price:,.0f}</b>"
            extra = '<div class="s1-lines">'
            for line_key, dot, name in [
                ("sth_realized_price", "var(--red)", "Short-term holder cost"),
                ("realized_price", "var(--gold)", "Average holder cost"),
                ("lth_realized_price", "var(--blue)", "Long-term holder cost"),
            ]:
                line_val = latest.get(line_key)
                shown = (
                    f"${float(line_val):,.0f}"
                    if line_val is not None and not pd.isna(line_val)
                    else "N/A"
                )
                extra += (
                    f'<div class="s1-line"><span class="s1-name">'
                    f'<span style="color:{dot};">●</span> {name}</span>'
                    f"<b>{shown}</b><span>{_rel_line(price, line_val)}</span></div>"
                )
            extra += "</div>"
            extra += (
                '<div class="card-dist">Below average cost = most holders underwater · '
                "below long-term cost = deep-value zone</div>"
            )
        elif key == "s2":
            mvrv = latest.get("mvrv")
            dev = latest.get("s2_dev")
            mvrv_txt = f"{float(mvrv):.2f}" if mvrv is not None and not pd.isna(mvrv) else "N/A"
            dev_txt = (
                f"{float(dev):+.2f}σ vs full-sample mean"
                if dev is not None and not pd.isna(dev)
                else "insufficient history"
            )
            now_html = f"Current MVRV <b>{mvrv_txt}</b> · {dev_txt}"
            extra = '<div class="card-dist">Further left = closer to historical bottoms</div>'
        elif key == "s3":
            loss = latest.get("supply_loss_pct")
            dev = latest.get("s3_dev")
            loss_txt = f"{float(loss):.1f}%" if loss is not None and not pd.isna(loss) else "N/A"
            dev_txt = (
                f"{float(dev):+.2f}σ" if dev is not None and not pd.isna(dev) else "n/a"
            )
            now_html = f"Supply in loss <b>{loss_txt}</b> · {dev_txt}"
            extra = (
                '<div class="card-dist">Bull tops ≈ 0-2% · bear bottoms reach 50%+ '
                "(supply-weighted)</div>"
            )
        elif key == "s4":
            flow = latest.get("realized_cap_change_30d_usd")
            pctile = latest.get("s4_pctile")
            pct_txt = (
                f"{float(pctile) * 100.0:.0f}th percentile"
                if pctile is not None and not pd.isna(pctile)
                else "insufficient history"
            )
            now_html = f"30d realized-cap change <b>{_fmt_usd_compact(flow)}</b> · {pct_txt}"
            extra = (
                '<div class="card-dist">Deep outflows historically cluster near '
                "capitulation lows</div>"
            )
        else:  # s5
            fng = latest.get("fear_greed")
            fng_txt = f"{float(fng):.0f}" if fng is not None and not pd.isna(fng) else "N/A"
            now_html = f"Fear &amp; Greed <b>{fng_txt}</b> · {_fng_classification(fng)}"
            extra = '<div class="card-dist">0 = extreme fear (bottoms) · 100 = extreme greed (tops)</div>'

        cards.append(
            {
                "key": key,
                "short": SIGNAL_SHORT_LABELS[key],
                "title": title,
                "subtitle": subtitle,
                "status": status,
                "color": color,
                "score_text": "–" if score_missing else f"{float(score):.1f}",
                "bar_pct": 0.0 if score_missing else round(5.0 * float(score), 1),
                "marker_pct": round(marker_pct(score), 1),
                "now_html": now_html,
                "extra_html": extra,
                "spark": sparkline_points(spark_window[key].tolist()),
            }
        )
    return cards


def generate_bottom_signals_page(
    scores_df: pd.DataFrame,
    price_df: pd.DataFrame,
    backtest: dict,
    output_path: Path = OUTPUT_HTML,
    info_path: Path = OUTPUT_INFO,
) -> dict:
    """Render the dashboard page and info JSON; return the snapshot dict.

    scores_df comes from compute_bottom_signal_scores (date-sorted), price_df
    is the full btc_metrics frame (for ATH / MA context beyond the on-chain
    window), backtest comes from build_backtest.
    """
    scored = scores_df[scores_df["composite"].notna()]
    if scored.empty:
        raise ValueError("no rows with a composite score; cannot render page")
    latest = scored.iloc[-1]

    closes = pd.to_numeric(price_df["close_price"], errors="coerce").dropna()
    price = float(latest["close_price"])
    # 24h change from the scored frame so it describes the same day as `price`
    # (the full price series can run ahead of the on-chain data date).
    scored_closes = pd.to_numeric(scored["close_price"], errors="coerce").dropna()
    chg24h = (
        (scored_closes.iloc[-1] / scored_closes.iloc[-2] - 1.0) * 100.0
        if len(scored_closes) >= 2
        else 0.0
    )
    ath = float(closes.max())
    ma120 = float(closes.rolling(120).mean().iloc[-1]) if len(closes) >= 120 else price
    ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else price

    composite = float(latest["composite"])
    zone_label, zone_color = zone_for(composite)
    advice = ZONE_ADVICE[zone_label]

    if price < ma120 and price < ma200:
        ma_comment = "Price below both averages (weak trend)"
    elif price > ma120 and price > ma200:
        ma_comment = "Price above both averages (strong trend)"
    else:
        ma_comment = "Price between the two averages (transition)"

    context = {
        "plotly_cdn": PLOTLY_CDN,
        "data_date": str(latest["date"]),
        "price": price,
        "chg24h_pct": chg24h,
        "ath": ath,
        "from_ath_pct": (price / ath - 1.0) * 100.0,
        "gauge": gauge_svg(composite, zone_label, zone_color),
        "zone": zone_label,
        "zone_color": zone_color,
        "advice": advice,
        "cards": _build_cards(latest, scores_df),
        "ma120": ma120,
        "ma200": ma200,
        "ma120_dist_pct": (price / ma120 - 1.0) * 100.0,
        "ma200_dist_pct": (price / ma200 - 1.0) * 100.0,
        "ma_comment": ma_comment,
        "thresholds": list(THRESHOLDS),
        "durations": list(DURATIONS),
        "matrix": backtest["matrix"],
        "cycle_bottoms_label": " and ".join(b[0][:7] for b in CYCLE_BOTTOMS),
        "dates_json": _json_for_script(scores_df["date"].tolist()),
        "prices_json": _json_for_script(
            [round(float(v), 2) for v in scores_df["close_price"]]
        ),
        "totals_json": _json_for_script(
            [
                None if pd.isna(v) else round(float(v), 2)
                for v in scores_df["composite"]
            ]
        ),
        "cycle_bots_json": _json_for_script(
            [{"date": d, "price": p} for d, p in CYCLE_BOTTOMS]
        ),
        "trig_json": _json_for_script(backtest["trig"]),
    }

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    html = env.get_template("bottom_signals.html.j2").render(**context)
    _atomic_write_text(Path(output_path), html)
    print(f"✓ Bottom signals page written to {output_path}")

    snapshot = {
        "date": str(latest["date"]),
        "price": price,
        "chg24h_pct": chg24h,
        "ath": ath,
        "from_ath_pct": (price / ath - 1.0) * 100.0,
        "composite": composite,
        "zone": zone_label,
        "zone_color": zone_color,
        "advice": advice,
        "signals": [
            {
                "key": key,
                "label": SIGNAL_SHORT_LABELS[key],
                "score": round(float(latest[key]), 1),
                "status": _status_for_score(latest[key])[0],
            }
            for key, _, _ in SIGNAL_DEFS
        ],
        "mvrv": None if pd.isna(latest.get("mvrv")) else float(latest["mvrv"]),
        "supply_loss_pct": None
        if pd.isna(latest.get("supply_loss_pct"))
        else float(latest["supply_loss_pct"]),
        "realized_cap_change_30d_usd": None
        if pd.isna(latest.get("realized_cap_change_30d_usd"))
        else float(latest["realized_cap_change_30d_usd"]),
        "fear_greed": None
        if pd.isna(latest.get("fear_greed"))
        else float(latest["fear_greed"]),
        "lth_realized_price": None
        if pd.isna(latest.get("lth_realized_price"))
        else float(latest["lth_realized_price"]),
        "realized_price": None
        if pd.isna(latest.get("realized_price"))
        else float(latest["realized_price"]),
        "sth_realized_price": None
        if pd.isna(latest.get("sth_realized_price"))
        else float(latest["sth_realized_price"]),
        "ma120": ma120,
        "ma200": ma200,
    }
    _atomic_write_text(Path(info_path), json.dumps(snapshot, indent=2))
    print(f"✓ Bottom signals info written to {info_path}")
    return snapshot
