"""
Visualization module for Bitcoin valuation analysis.

This module provides interactive charts using Plotly to visualize:
- DCA and Trend ratios over time
- Double undervaluation zones
- Price vs fair value comparisons
"""

from pathlib import Path
from typing import Tuple
import html
import json
import re
import tempfile
import webbrowser

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .signal_backtest import known_rank

# Days of history a macro component needs before it is ranked
MACRO_RANK_MIN_HISTORY = 180

MACRO_RISK_SCORE_WEIGHTS = {
    "net_liquidity_90d_change": 0.35,
    "sofr": 0.20,
    "move": 0.20,
    "hy_oas": 0.25,
}


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text via temp file + atomic replace to tolerate read-only target files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _write_figure_html_atomic(fig: go.Figure, output_path: Path, **kwargs) -> None:
    """
    Persist Plotly HTML via temp file + replace.

    This avoids failures when target html exists but current user lacks direct
    write permission on that specific file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    auto_open = bool(kwargs.pop("auto_open", False))
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        fig.write_html(str(tmp_path), auto_open=False, **kwargs)
        tmp_path.replace(output_path)

        if auto_open:
            webbrowser.open(output_path.resolve().as_uri())
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def get_output_dir() -> Path:
    """
    Get the output directory for saving charts.

    Returns:
        Path object for the charts directory (inside docs/ for GitHub Pages)
    """
    project_root = Path(__file__).parent.parent.parent
    charts_dir = project_root / "docs" / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    return charts_dir


TEMPLATES_DIR = Path(__file__).parent / "templates"

CHART_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "scrollZoom": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "toImage"],
}

_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_LINE_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _split_chart_title(title_text: str) -> tuple[str, list[str]]:
    """Split a Plotly title into plain title text and subtitle segments."""
    lines = [_TAG_RE.sub("", line).strip() for line in _LINE_BREAK_RE.split(title_text or "")]
    lines = [line for line in lines if line]
    if not lines:
        return "", []
    segments = [
        segment.strip()
        for line in lines[1:]
        for segment in line.split("|")
        if segment.strip()
    ]
    return lines[0], segments


def _chart_header_html(title: str, segments: list[str]) -> str:
    items = "".join(
        f'<span class="chart-sub-item">{html.escape(segment)}</span>' for segment in segments
    )
    subtitle = f'<p class="chart-subtitle">{items}</p>' if items else ""
    return (
        '<header class="chart-header">'
        f'<div class="chart-heading"><h1 class="chart-title">{html.escape(title)}</h1>{subtitle}</div>'
        '<div class="chart-header-actions" id="chart-header-actions">'
        '<div class="chart-presets" id="chart-presets" role="group" aria-label="Time range"></div>'
        "</div></header>"
    )


def write_chart_html(fig: go.Figure, output_path: Path, auto_open: bool = False) -> None:
    """
    Write a chart page that fills the frame it is embedded in.

    The homepage owns the chart size, so the figure gets no fixed height or
    width. The Plotly title moves into an HTML header (Plotly titles cannot
    wrap on narrow screens), all charts share one plotly.min.js next to them,
    and the chart runtime adds time presets, y-axis fitting and touch modes.
    """
    output_path = Path(output_path)
    title, segments = _split_chart_title(fig.layout.title.text or "")
    fig.update_layout(title_text="", height=None, width=None, autosize=True)
    fig.update_layout(margin=dict(t=30, b=40))
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    # Dates on the time axis are self-explanatory
    fig.for_each_xaxis(
        lambda axis: axis.update(title_text="")
        if (axis.title.text or "").strip().lower() == "date"
        else None
    )
    if fig.layout.legend.orientation == "h":
        # Size legend entries by their text so they wrap instead of overlapping
        fig.update_layout(
            legend=dict(
                x=0,
                xanchor="left",
                y=1.02,
                yanchor="bottom",
                entrywidth=0,
                entrywidthmode="pixels",
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
            )
        )

    _write_figure_html_atomic(
        fig,
        output_path,
        auto_open=auto_open,
        include_plotlyjs="directory",
        default_height="100%",
        default_width="100%",
        config=CHART_CONFIG,
    )

    page = output_path.read_text(encoding="utf-8")
    style = (TEMPLATES_DIR / "chart_runtime.css").read_text(encoding="utf-8")
    script = (TEMPLATES_DIR / "chart_runtime.js").read_text(encoding="utf-8")
    head = (
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<style id="chart-runtime-style">{style}</style>'
        f'<script id="chart-runtime">{script}</script>'
    )
    page, head_count = re.subn(r"<head>", lambda _: "<head>" + head, page, count=1)
    page, body_count = re.subn(
        r"<body>\s*<div>",
        lambda _: "<body>" + _chart_header_html(title, segments) + '<div class="chart-plot">',
        page,
        count=1,
    )
    if head_count != 1 or body_count != 1:
        raise ValueError(f"Unexpected Plotly HTML layout in {output_path}")
    _atomic_write_text(output_path, page)


def add_info_modal_script(html_path: Path, title: str, content_html: str) -> None:
    """
    Add a reusable info button + modal popup to a generated chart HTML.

    Args:
        html_path: Path to the HTML chart file
        title: Modal title text
        content_html: Modal body HTML
    """
    if not html_path.exists():
        return

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    marker = "chart-info-button"
    if marker in html_content:
        return

    info_script = f"""
    <script>
    (function() {{
        var modalTitle = {json.dumps(title)};
        var modalContent = {json.dumps(content_html)};

        function ensureStyles() {{
            if (document.getElementById('chart-info-modal-style')) return;
            var style = document.createElement('style');
            style.id = 'chart-info-modal-style';
            style.textContent = `
                .chart-info-button {{
                    position: fixed;
                    top: 14px;
                    left: 14px;
                    width: 30px;
                    height: 30px;
                    border-radius: 50%;
                    border: 1px solid rgba(0,0,0,0.25);
                    background: rgba(255,255,255,0.95);
                    color: #2f4668;
                    font-size: 18px;
                    font-weight: 700;
                    line-height: 1;
                    cursor: pointer;
                    z-index: 9999;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.18);
                }}
                .chart-info-modal-overlay {{
                    position: fixed;
                    inset: 0;
                    background: rgba(0, 0, 0, 0.42);
                    display: none;
                    align-items: center;
                    justify-content: center;
                    z-index: 10000;
                }}
                .chart-info-modal {{
                    width: min(760px, 92vw);
                    max-height: 84vh;
                    overflow-y: auto;
                    background: #ffffff;
                    border-radius: 10px;
                    border: 1px solid rgba(0,0,0,0.18);
                    box-shadow: 0 10px 40px rgba(0,0,0,0.28);
                    color: #1d2f4a;
                    padding: 18px 20px 16px 20px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }}
                .chart-info-modal-head {{
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 10px;
                }}
                .chart-info-modal-title {{
                    font-size: 20px;
                    font-weight: 700;
                    margin: 0;
                }}
                .chart-info-modal-close {{
                    border: none;
                    background: transparent;
                    font-size: 24px;
                    line-height: 1;
                    color: #44546a;
                    cursor: pointer;
                }}
                .chart-info-modal-body {{
                    font-size: 15px;
                    line-height: 1.6;
                }}
                .chart-info-modal-body h4 {{
                    margin: 12px 0 6px 0;
                    font-size: 16px;
                }}
                .chart-info-modal-body p {{
                    margin: 6px 0;
                }}
                .chart-info-modal-body code {{
                    background: #f0f4fa;
                    border: 1px solid #d8e2f1;
                    border-radius: 4px;
                    padding: 1px 4px;
                }}
            `;
            document.head.appendChild(style);
        }}

        function createModal() {{
            ensureStyles();

            var btn = document.createElement('button');
            btn.className = 'chart-info-button';
            btn.id = 'chart-info-button';
            btn.type = 'button';
            btn.title = 'Open chart guide';
            btn.setAttribute('aria-label', 'Open chart guide');
            btn.textContent = 'i';

            var overlay = document.createElement('div');
            overlay.className = 'chart-info-modal-overlay';
            overlay.id = 'chart-info-modal-overlay';

            var modal = document.createElement('div');
            modal.className = 'chart-info-modal';
            modal.innerHTML = `
                <div class="chart-info-modal-head">
                    <h3 class="chart-info-modal-title"></h3>
                    <button class="chart-info-modal-close" type="button" aria-label="Close">×</button>
                </div>
                <div class="chart-info-modal-body"></div>
            `;

            modal.querySelector('.chart-info-modal-title').textContent = modalTitle;
            modal.querySelector('.chart-info-modal-body').innerHTML = modalContent;
            overlay.appendChild(modal);

            function openModal() {{
                overlay.style.display = 'flex';
                document.body.style.overflow = 'hidden';
            }}
            function closeModal() {{
                overlay.style.display = 'none';
                document.body.style.overflow = '';
            }}

            btn.addEventListener('click', openModal);
            overlay.addEventListener('click', function(evt) {{
                if (evt.target === overlay) closeModal();
            }});
            modal.querySelector('.chart-info-modal-close').addEventListener('click', closeModal);
            document.addEventListener('keydown', function(evt) {{
                if (evt.key === 'Escape' && overlay.style.display === 'flex') closeModal();
            }});

            var actions = document.getElementById('chart-header-actions');
            if (actions) {{
                actions.insertBefore(btn, actions.firstChild);
            }} else {{
                document.body.appendChild(btn);
            }}
            document.body.appendChild(overlay);
        }}

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', createModal);
        }} else {{
            createModal();
        }}
    }})();
    </script>
    """

    if "</body>" in html_content:
        html_content = html_content.replace("</body>", info_script + "\n</body>")
        _atomic_write_text(html_path, html_content)


def plot_valuation_ratios(
    df: pd.DataFrame,
    output_filename: str = "valuation_ratios.html",
    auto_open: bool = True,
) -> str:
    """
    Create an interactive plot of valuation ratios with double undervaluation zones highlighted.

    This plot shows:
    - ratio_dca (Price/DCA) over time
    - ratio_trend (Price/Trend) over time
    - ahr999 index over time
    - Horizontal line at y=1.0 (fair value threshold)
    - Shaded regions where both ratios < 1.0 (buy zones)
    - ahr999 zone thresholds (0.45 bottom, 1.2 watch)

    Args:
        df: DataFrame with date, ratio_dca, ratio_trend, ahr999, and is_double_undervalued columns
        output_filename: Name of the output HTML file (default: "valuation_ratios.html")
        auto_open: Whether to automatically open the chart in browser (default: True)

    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data (where metrics exist)
    plot_df = df.dropna(subset=["ratio_dca", "ratio_trend", "ahr999"]).copy()

    # Create figure
    fig = go.Figure()

    # Add shaded regions for double undervaluation zones
    # Find contiguous periods where both ratios < 1
    # Reset index to ensure we have continuous integer indices
    plot_df = plot_df.reset_index(drop=True)

    double_uv_periods = []
    in_period = False
    start_pos = None

    for pos in range(len(plot_df)):
        is_double_uv = plot_df.iloc[pos]["is_double_undervalued"]

        if is_double_uv and not in_period:
            # Start of new period
            in_period = True
            start_pos = pos
        elif not is_double_uv and in_period:
            # End of period
            in_period = False
            double_uv_periods.append((start_pos, pos - 1))

    # Handle case where period extends to end of data
    if in_period:
        double_uv_periods.append((start_pos, len(plot_df) - 1))

    # Add shaded rectangles for each double undervaluation period
    for start_pos, end_pos in double_uv_periods:
        start_date = plot_df.iloc[start_pos]["date"]
        end_date = plot_df.iloc[end_pos]["date"]

        fig.add_vrect(
            x0=start_date,
            x1=end_date,
            fillcolor="red",
            opacity=0.15,
            layer="below",
            line_width=0,
        )

    # Add ratio_dca line
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["ratio_dca"],
            mode="lines",
            name="Price/DCA Ratio",
            line=dict(color="rgb(31, 119, 180)", width=2),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>Price/DCA:</b> %{y:.3f}<br>"
            + "<extra></extra>",
        )
    )

    # Add ratio_trend line
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["ratio_trend"],
            mode="lines",
            name="Price/Trend Ratio",
            line=dict(color="rgb(44, 160, 44)", width=2),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>Price/Trend:</b> %{y:.3f}<br>"
            + "<extra></extra>",
        )
    )

    # Add ahr999 index line
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["ahr999"],
            mode="lines",
            name="ahr999 Index",
            line=dict(color="rgb(255, 127, 14)", width=3),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>ahr999:</b> %{y:.3f}<br>"
            + "<extra></extra>",
        )
    )

    # Add horizontal line at y=1.0 (fair value threshold)
    fig.add_hline(
        y=1.0,
        line_dash="dash",
        line_color="gray",
        line_width=1.5,
    )
    fig.add_annotation(
        x=0.99,
        y=1.0,
        xref="paper",
        yref="y",
        text="Fair Value (1.0)",
        showarrow=False,
        xanchor="right",
        yanchor="bottom",
        yshift=5,
        font=dict(color="gray", size=10),
        bgcolor="rgba(255, 255, 255, 0.6)",
    )

    # Add ahr999 threshold lines
    fig.add_hline(
        y=0.45,
        line_dash="dot",
        line_color="rgb(40, 167, 69)",
        line_width=2,
    )
    # Annotation positions on a log axis are given in log10 units
    fig.add_annotation(
        x=0.01,
        y=np.log10(0.45),
        xref="paper",
        yref="y",
        text="🔥 ahr999 Bottom Zone (0.45)",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        yshift=5,
        font=dict(color="rgb(40, 167, 69)", size=10),
        bgcolor="rgba(255, 255, 255, 0.6)",
    )

    fig.add_hline(
        y=1.2,
        line_dash="dot",
        line_color="rgb(255, 149, 0)",
        line_width=2,
    )
    fig.add_annotation(
        x=0.01,
        y=np.log10(1.2),
        xref="paper",
        yref="y",
        text="⚠️ ahr999 Watch Zone (1.2)",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        yshift=5,
        font=dict(color="rgb(255, 149, 0)", size=10),
        bgcolor="rgba(255, 255, 255, 0.6)",
    )

    # Update layout
    fig.update_layout(
        title={
            "text": "Bitcoin Valuation Ratios & ahr999 Index<br><sub>Red shaded areas = Double Undervaluation | ahr999 < 0.45 = Bottom Zone | ahr999 < 1.2 = DCA Zone</sub>",
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis_title="Date",
        yaxis_title="Ratio Value (log)",
        yaxis=dict(
            # Early ahr999 values reach ~35; a linear axis flattens recent 0.4-1.5 moves
            type="log",
            tickmode="array",
            tickvals=[0.2, 0.3, 0.5, 1, 2, 3, 5, 10, 20, 30],
            ticktext=["0.2", "0.3", "0.5", "1", "2", "3", "5", "10", "20", "30"],
            autorange=True,
            fixedrange=False,
        ),
        hovermode="x unified",
        template="plotly_white",
        height=650,
        showlegend=True,
        legend=dict(orientation="h"),
    )

    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)

    print(f"✓ Saved interactive chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")

    return str(output_path)


def plot_price_comparison(
    df: pd.DataFrame,
    output_filename: str = "price_comparison.html",
    auto_open: bool = False,
) -> str:
    """
    Create an interactive plot comparing actual price with DCA and Trend fair values.

    Args:
        df: DataFrame with date, close_price, dca_cost, and trend_value columns
        output_filename: Name of the output HTML file (default: "price_comparison.html")
        auto_open: Whether to automatically open the chart in browser (default: False)

    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data
    plot_df = df.dropna(subset=["dca_cost", "trend_value"]).copy()

    # Create figure
    fig = go.Figure()

    # Add actual price
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["close_price"],
            mode="lines",
            name="Price",  # Shortened legend text
            line=dict(color="black", width=2),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>Price:</b> $%{y:,.2f}<br>"
            + "<extra></extra>",
        )
    )

    # Add DCA cost
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["dca_cost"],
            mode="lines",
            name="DCA",  # Shortened legend text
            line=dict(color="rgb(31, 119, 180)", width=2, dash="dash"),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>DCA Cost:</b> $%{y:,.2f}<br>"
            + "<extra></extra>",
        )
    )

    # Add trend value
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["trend_value"],
            mode="lines",
            name="Trend",  # Shortened legend text
            line=dict(color="rgb(44, 160, 44)", width=2, dash="dot"),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>Trend:</b> $%{y:,.2f}<br>"
            + "<extra></extra>",
        )
    )

    # Highlight double undervaluation zones
    double_uv_df = plot_df[plot_df["is_double_undervalued"]].copy()
    if not double_uv_df.empty:
        fig.add_trace(
            go.Scatter(
                x=double_uv_df["date"],
                y=double_uv_df["close_price"],
                mode="markers",
                name="Buy Zone",  # Shortened legend text
                marker=dict(
                    color="red",
                    size=8,
                    symbol="circle",
                    line=dict(color="darkred", width=1),
                ),
                hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
                + "<b>Price:</b> $%{y:,.2f}<br>"
                + "<b>🎯 Double Undervalued!</b><br>"
                + "<extra></extra>",
            )
        )

    # Update layout
    fig.update_layout(
        title={
            "text": "Bitcoin Price vs Fair Value Indicators<br>",
            "x": 0.5,
            "xanchor": "center",
            "y": 0.97,  # Position title closer to the top border (relative units)
            "yanchor": "top",
        },
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        yaxis=dict(
            type="log",  # Log scale to better show the power law growth
            autorange=True,  # Enable auto-scaling for y-axis
            fixedrange=False,  # Allow y-axis to be zoomed and auto-adjusted
        ),
        hovermode="x unified",
        template="plotly_white",
        height=700,
        showlegend=True,
        legend=dict(
            orientation="h",  # Horizontal layout
            yanchor="bottom",
            y=1.05,  # Place legend just above the plot area (relative units)
            xanchor="center",
            x=0.5,  # Center the legend frame
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor="rgba(0, 0, 0, 0.15)",
            borderwidth=1,
            itemsizing="constant",  # Consistent item sizing
            entrywidthmode="fraction",  # Use relative legend entry width for responsiveness
            entrywidth=0.22,  # Allocate ~22% width to each entry to separate icon and text
            font=dict(size=11),  # Balanced font size for readability
        ),
        margin=dict(t=120),  # Provide enough top margin for title + legend stack
    )

    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)

    print(f"✓ Saved price comparison chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")

    return str(output_path)


def plot_double_undervaluation_stats(
    df: pd.DataFrame,
    output_filename: str = "double_uv_stats.html",
    auto_open: bool = False,
) -> str:
    """
    Create statistical charts about double undervaluation occurrences.

    Shows:
    - Distribution of double undervaluation by year (Dual Axis: Days + Percentage)
    - Normalized BTC Price trend

    Args:
        df: DataFrame with valuation metrics
        output_filename: Name of the output HTML file
        auto_open: Whether to automatically open the chart in browser

    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data
    plot_df = df.dropna(subset=["ratio_dca", "ratio_trend"]).copy()

    # Add year column
    plot_df["year"] = plot_df["date"].dt.year

    # 1. Calculate yearly stats for undervaluation
    yearly_stats = (
        plot_df.groupby("year")
        .agg(
            {
                "is_double_undervalued": ["sum", "count"],
                "close_price": "mean",  # Calculate average price per year
            }
        )
        .reset_index()
    )

    # Flatten columns
    yearly_stats.columns = ["year", "double_uv_days", "total_days", "avg_price"]

    # Calculate percentage
    yearly_stats["percentage"] = (
        yearly_stats["double_uv_days"] / yearly_stats["total_days"]
    ) * 100

    # 2. Calculate Normalized BTC Price Index (0-100)
    min_price = yearly_stats["avg_price"].min()
    max_price = yearly_stats["avg_price"].max()

    # Avoid division by zero if min == max
    if max_price > min_price:
        yearly_stats["price_index"] = (
            100 * (yearly_stats["avg_price"] - min_price) / (max_price - min_price)
        )
    else:
        yearly_stats["price_index"] = 50  # Default if flat

    # Create dual-axis chart
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 1. Bar chart: Absolute days (Left Axis)
    fig.add_trace(
        go.Bar(
            x=yearly_stats["year"],
            y=yearly_stats["double_uv_days"],
            name="Days",
            marker_color="rgb(220, 53, 69)",  # Red
            opacity=0.7,
            hovertemplate="<b>Year:</b> %{x}<br>"
            + "<b>Days:</b> %{y}<br>"
            + "<extra></extra>",
        ),
        secondary_y=False,
    )

    # 2. Line chart: Percentage (Right Axis)
    fig.add_trace(
        go.Scatter(
            x=yearly_stats["year"],
            y=yearly_stats["percentage"],
            name="% of days in zone",
            mode="lines+markers",
            marker=dict(size=8, color="rgb(255, 140, 0)"),  # Dark Orange
            line=dict(width=3, color="rgb(255, 140, 0)"),
            hovertemplate="<b>Year:</b> %{x}<br>"
            + "<b>Percentage:</b> %{y:.1f}%<br>"
            + "<extra></extra>",
        ),
        secondary_y=True,
    )

    # 3. Line chart: Normalized Price Index (Right Axis)
    fig.add_trace(
        go.Scatter(
            x=yearly_stats["year"],
            y=yearly_stats["price_index"],
            name="BTC price index",
            mode="lines+markers",
            marker=dict(size=6, symbol="diamond", color="#2c3e50"),  # Dark Blue/Grey
            line=dict(width=2, color="#2c3e50", dash="dot"),
            hovertemplate="<b>Year:</b> %{x}<br>"
            + "<b>Price Index:</b> %{y:.1f} (Avg: $%{customdata:,.0f})<br>"
            + "<extra></extra>",
            customdata=yearly_stats["avg_price"],
        ),
        secondary_y=True,
    )

    # Update layout
    fig.update_layout(
        title=dict(
            text="Double Undervaluation Statistics by Year",
            y=0.96,
            x=0.5,
            xanchor="center",
            yanchor="top",
        ),
        height=550,
        template="plotly_white",
        showlegend=False,  # Disable standard legend
        margin=dict(l=60, r=60, t=80, b=50),
        hovermode="x unified",
    )

    # Add custom legend as annotation (to avoid clipping)
    fig.add_annotation(
        text=(
            "<span style='color:#dc3545; font-size:14px'>■</span> Days<br>"
            + "<span style='color:#ff8c00; font-size:14px'>●</span> % of days in zone<br>"
            + "<span style='color:#2c3e50; font-size:14px'>♦</span> BTC price index"
        ),
        xref="paper",
        yref="paper",
        x=0.02,
        y=0.98,  # Top-left inside plot
        xanchor="left",
        yanchor="top",
        showarrow=False,
        align="left",
        font=dict(size=12, color="#333"),
        bgcolor="rgba(255, 255, 255, 0.9)",
        bordercolor="#e5e5e5",
        borderwidth=1,
        borderpad=6,
    )

    # Configure X-axis (Show every year)
    fig.update_xaxes(
        title_text="Year",
        tickmode="linear",
        dtick=1,  # Force label for every year
        tickangle=-45 if len(yearly_stats) > 10 else 0,  # Rotate if many years
    )

    # Configure Y-axes
    fig.update_yaxes(
        title_text="Days", secondary_y=False, showgrid=True, gridcolor="#f0f0f0"
    )

    fig.update_yaxes(
        title_text="Percentage (%) / Normalized BTC Price (0-100)",
        secondary_y=True,
        range=[0, 105],  # Fixed range 0-100%
        showgrid=False,
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)

    print(f"✓ Saved statistics chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")

    return str(output_path)


def plot_usdjpy(
    df: pd.DataFrame,
    output_filename: str = "usdjpy.html",
    auto_open: bool = False,
) -> str:
    """
    Create an interactive plot of USD/JPY exchange rate with key thresholds.

    Args:
        df: DataFrame with date and close_price columns (USD/JPY rate)
        output_filename: Name of the output HTML file (default: "usdjpy.html")
        auto_open: Whether to automatically open the chart in browser (default: False)

    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data
    plot_df = df.dropna(subset=["close_price"]).copy()

    # Get current rate for status display
    current_rate = plot_df["close_price"].iloc[-1]

    # Define key thresholds (important psychological and historical levels)
    thresholds = [
        (100, "100 (Historical Low Zone)", "rgb(40, 167, 69)"),  # Green - very weak USD
        (110, "110", "rgb(100, 200, 100)"),  # Light green
        (120, "120", "rgb(150, 150, 150)"),  # Gray - neutral
        (130, "130", "rgb(200, 150, 100)"),  # Light orange
        (140, "140", "rgb(255, 149, 0)"),  # Orange
        (150, "150 (Strong USD Zone)", "rgb(255, 100, 100)"),  # Light red
        (160, "160 (Very Strong USD)", "rgb(220, 53, 69)"),  # Red - very strong USD
    ]

    # Create figure
    fig = go.Figure()

    # Add USD/JPY line
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["close_price"],
            mode="lines",
            name="USD/JPY",
            line=dict(color="rgb(31, 119, 180)", width=2),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>USD/JPY:</b> %{y:.2f}<br>"
            + "<extra></extra>",
        )
    )

    # Add current rate marker
    fig.add_trace(
        go.Scatter(
            x=[plot_df["date"].iloc[-1]],
            y=[current_rate],
            mode="markers+text",
            name="Current",
            marker=dict(
                color="red",
                size=12,
                symbol="circle",
                line=dict(color="darkred", width=2),
            ),
            text=[f"Current: {current_rate:.2f}"],
            textposition="top center",
            hovertemplate="<b>Current Rate:</b> %{y:.2f}<br>"
            + "<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<extra></extra>",
        )
    )

    # Add threshold lines
    for threshold_value, label, color in thresholds:
        # Determine if current rate is above or below threshold
        is_above = current_rate >= threshold_value

        # Add horizontal line
        fig.add_hline(
            y=threshold_value,
            line_dash="dash" if threshold_value in [100, 150, 160] else "dot",
            line_color=color,
            line_width=2 if threshold_value in [100, 150, 160] else 1,
            annotation_text=label,
            annotation_position="right" if is_above else "left",
            annotation_font_color=color,
            annotation_font_size=11 if threshold_value in [100, 150, 160] else 9,
        )

    # Determine current level status
    if current_rate < 110:
        status = "Very Weak USD (Below 110)"
    elif current_rate < 120:
        status = "Weak USD (110-120)"
    elif current_rate < 130:
        status = "Moderate (120-130)"
    elif current_rate < 140:
        status = "Moderate-Strong (130-140)"
    elif current_rate < 150:
        status = "Strong USD (140-150)"
    elif current_rate < 160:
        status = "Very Strong USD (150-160)"
    else:
        status = "Extreme USD (>160)"

    # Update layout
    fig.update_layout(
        title={
            "text": f"USD/JPY Exchange Rate<br><sub>Current: {current_rate:.2f} ({status})</sub>",
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis_title="Date",
        yaxis_title="USD/JPY",
        yaxis=dict(
            autorange=True,
            fixedrange=False,
        ),
        hovermode="x unified",
        template="plotly_white",
        height=600,
        showlegend=False,
    )

    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)

    print(f"✓ Saved USD/JPY chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")

    return str(output_path)


def plot_usdjpy_risk_map(
    usdjpy_df: pd.DataFrame,
    yield_df: pd.DataFrame,
    data_source: str = "FRED / Yahoo Finance",
    output_filename: str = "usdjpy_risk_map.html",
    auto_open: bool = False,
) -> str:
    """
    Create a USD/JPY Systemic Risk Map chart combining FX level and yield spread.

    This chart visualizes carry-trade blow-up risk with:
    - USD/JPY spot price (left axis)
    - US-Japan 2-year yield spread (right axis)
    - Color-coded risk zones based on USD/JPY levels
    - Key signal lines for yield spreads

    Args:
        usdjpy_df: DataFrame with date and close_price columns (USD/JPY rate)
        yield_df: DataFrame with date, us_2y, jp_2y, and spread columns
        data_source: Source of the yield data (e.g., "FRED" or "Yahoo Finance")
        output_filename: Name of the output HTML file
        auto_open: Whether to automatically open the chart in browser

    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data
    usdjpy_plot = usdjpy_df.dropna(subset=["close_price"]).copy()
    yield_plot = yield_df.dropna(subset=["spread"]).copy()

    # Merge data on date
    # Use left join on USD/JPY to keep all price data
    merged = pd.merge(
        usdjpy_plot,
        yield_plot,
        on="date",
        how="left",
    )

    if merged.empty:
        raise ValueError("No USD/JPY data available")

    # Forward fill yield data for recent days (systemic risk doesn't change hourly)
    merged["spread"] = merged["spread"].ffill()
    merged["us_2y"] = merged["us_2y"].ffill()
    merged["jp_2y"] = merged["jp_2y"].ffill()

    # Drop rows where we still don't have data (beginning of time)
    merged = merged.dropna(subset=["spread", "close_price"])

    # Get current values
    current_rate = merged["close_price"].iloc[-1]
    current_spread = merged["spread"].iloc[-1]

    # Create subplots with secondary y-axis
    fig = make_subplots(
        rows=1,
        cols=1,
        specs=[[{"secondary_y": True}]],
        # Removed subplot title to avoid duplication
    )

    # Add USD/JPY line (primary y-axis, left)
    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["close_price"],
            mode="lines",
            name="USD/JPY",
            line=dict(color="rgb(31, 119, 180)", width=2),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>USD/JPY:</b> %{y:.2f}<br>"
            + "<extra></extra>",
        ),
        secondary_y=False,
    )

    # Add yield spread line (secondary y-axis, right)
    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["spread"],
            mode="lines",
            name="US-Japan 2Y Spread",
            line=dict(color="rgb(255, 127, 14)", width=2, dash="dash"),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<b>Spread:</b> %{y:.2f}%<br>"
            + "<b>US 2Y:</b> %{customdata[0]:.2f}%<br>"
            + "<b>JP 2Y:</b> %{customdata[1]:.2f}%<br>"
            + "<extra></extra>",
            customdata=merged[["us_2y", "jp_2y"]].values,
        ),
        secondary_y=True,
    )

    # Add current rate marker
    fig.add_trace(
        go.Scatter(
            x=[merged["date"].iloc[-1]],
            y=[current_rate],
            mode="markers+text",
            name="Current USD/JPY",
            marker=dict(
                color="red",
                size=12,
                symbol="circle",
                line=dict(color="darkred", width=2),
            ),
            text=[f"{current_rate:.2f}"],
            textposition="top center",
            hovertemplate="<b>Current USD/JPY:</b> %{y:.2f}<br>"
            + "<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<extra></extra>",
        ),
        secondary_y=False,
    )

    # Add current spread marker
    fig.add_trace(
        go.Scatter(
            x=[merged["date"].iloc[-1]],
            y=[current_spread],
            mode="markers+text",
            name="Current Spread",
            marker=dict(
                color="orange",
                size=12,
                symbol="diamond",
                line=dict(color="darkorange", width=2),
            ),
            text=[f"{current_spread:.2f}%"],
            textposition="bottom center",
            hovertemplate="<b>Current Spread:</b> %{y:.2f}%<br>"
            + "<b>Date:</b> %{x|%Y-%m-%d}<br>"
            + "<extra></extra>",
        ),
        secondary_y=True,
    )

    # Define risk zones (based on USD/JPY level)
    risk_zones = [
        (135, 142, "SAFE ZONE", "rgba(40, 167, 69, 0.2)", "rgb(40, 167, 69)"),
        (142, 150, "NEUTRAL ZONE", "rgba(255, 193, 7, 0.2)", "rgb(255, 193, 7)"),
        (150, 155, "WARNING ZONE", "rgba(255, 149, 0, 0.2)", "rgb(255, 149, 0)"),
        (155, 160, "DANGER ZONE", "rgba(220, 53, 69, 0.3)", "rgb(220, 53, 69)"),
        (160, 200, "SYSTEMIC-RISK ZONE", "rgba(139, 0, 0, 0.3)", "rgb(139, 0, 0)"),
    ]

    # Add risk zone rectangles (on primary y-axis)
    for zone_min, zone_max, zone_name, fill_color, line_color in risk_zones:
        fig.add_hrect(
            y0=zone_min,
            y1=zone_max,
            fillcolor=fill_color,
            layer="below",
            line_width=0,
            annotation_text=zone_name,
            annotation_position="top left",  # Move to left to avoid overlap
            annotation_font_size=10,
            annotation_font_color=line_color,
            row=1,
            col=1,
        )

    # Add key spread signal lines (on secondary y-axis)
    # Note: add_hline doesn't support secondary_y directly, so we add them as shapes
    fig.add_shape(
        type="line",
        x0=merged["date"].min(),
        x1=merged["date"].max(),
        y0=2.5,
        y1=2.5,
        yref="y2",  # Reference secondary y-axis
        line=dict(color="rgb(40, 167, 69)", width=2, dash="dash"),
    )
    fig.add_annotation(
        x=merged["date"].max(),
        y=2.5,
        yref="y2",
        text="Spread = 2.5% (USD-bullish)",
        showarrow=False,
        xanchor="right",
        yanchor="bottom",  # Move slightly up
        font=dict(color="rgb(40, 167, 69)", size=10),
        bgcolor="rgba(255, 255, 255, 0.6)",
    )

    fig.add_shape(
        type="line",
        x0=merged["date"].min(),
        x1=merged["date"].max(),
        y0=2.0,
        y1=2.0,
        yref="y2",  # Reference secondary y-axis
        line=dict(color="rgb(220, 53, 69)", width=2, dash="dash"),
    )
    fig.add_annotation(
        x=merged["date"].max(),
        y=2.0,
        yref="y2",
        text="Spread = 2.0% (Blow-up risk)",
        showarrow=False,
        xanchor="right",
        yanchor="bottom",  # Move slightly up
        font=dict(color="rgb(220, 53, 69)", size=10),
        bgcolor="rgba(255, 255, 255, 0.6)",
    )

    # Calculate current risk level
    risk_level, risk_description = calculate_risk_level(current_rate, current_spread)

    # Update layout
    fig.update_layout(
        title={
            "text": f"USD/JPY Systemic Risk Map<br><sub>Current: {current_rate:.2f} | Spread: {current_spread:.2f}% | Risk: {risk_level}</sub>",
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis_title="Date",
        hovermode="x unified",
        template="plotly_white",
        height=750,  # Standardized height
        showlegend=True,
        legend=dict(
            orientation="h",  # Horizontal layout
            yanchor="bottom",
            y=1.02,  # Place legend just above the plot area
            xanchor="center",
            x=0.5,  # Center the legend frame
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor="rgba(0, 0, 0, 0.15)",
            borderwidth=1,
            itemsizing="constant",
            entrywidthmode="fraction",
            entrywidth=0.20,  # Allocate width for responsiveness
            font=dict(size=11),
        ),
        margin=dict(t=140, b=260, r=50, l=50),  # Increased bottom margin for rules text
    )

    # Update y-axes
    fig.update_yaxes(
        title_text="USD/JPY Rate",
        autorange=True,
        fixedrange=False,
        secondary_y=False,
    )

    fig.update_yaxes(
        title_text="US-Japan 2Y Yield Spread (%)",
        autorange=True,
        fixedrange=False,
        secondary_y=True,
    )

    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)
    add_info_modal_script(
        output_path,
        "USD/JPY Risk Rules",
        (
            "<h4>Combined risk rules</h4>"
            "<p><b>Highest Risk (Systemic Crisis):</b> USD/JPY ≥ 155 AND Spread &lt; 2.0%</p>"
            "<p><b>Very High Risk:</b> USD/JPY ≥ 150 AND Spread &lt; 2.0%</p>"
            "<p><b>Elevated Risk:</b> USD/JPY ≥ 150 AND Spread 2.0-2.5%</p>"
            "<p><b>Neutral:</b> USD/JPY 142-150 AND Spread &gt; 2.5%</p>"
            "<p><b>Safe:</b> USD/JPY 135-142 AND Spread &gt; 2.5%</p>"
            f"<h4>Current status</h4><p>{html.escape(risk_description)}</p>"
            f"<p>Data source: {html.escape(data_source)}</p>"
        ),
    )

    print(f"✓ Saved USD/JPY Risk Map chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")

    return str(output_path)


def calculate_risk_level(usdjpy_rate: float, spread: float) -> Tuple[str, str]:
    """
    Calculate risk level based on USD/JPY rate and yield spread.

    Returns:
        Tuple of (risk_level, description)
    """
    # Case 1: Highest Risk (Systemic Crisis Potential)
    if usdjpy_rate >= 155 and spread < 2.0:
        return (
            "HIGHEST RISK",
            f"Systemic Crisis Potential - USD/JPY {usdjpy_rate:.2f} ≥ 155 AND Spread {spread:.2f}% < 2.0%",
        )

    # Case 2: Very High Risk
    if usdjpy_rate >= 150 and spread < 2.0:
        return (
            "VERY HIGH RISK",
            f"Very High Risk - USD/JPY {usdjpy_rate:.2f} ≥ 150 AND Spread {spread:.2f}% < 2.0%",
        )

    # Case 3: Elevated Risk
    if usdjpy_rate >= 150 and 2.0 <= spread < 2.5:
        return (
            "ELEVATED RISK",
            f"Elevated Risk - USD/JPY {usdjpy_rate:.2f} ≥ 150 AND Spread {spread:.2f}% between 2.0-2.5%",
        )

    # Case 4: Neutral
    if 142 <= usdjpy_rate < 150 and spread > 2.5:
        return (
            "NEUTRAL",
            f"Neutral - USD/JPY {usdjpy_rate:.2f} between 142-150 AND Spread {spread:.2f}% > 2.5%",
        )

    # Case 5: Safe
    if 135 <= usdjpy_rate < 142 and spread > 2.5:
        return (
            "SAFE",
            f"Safe - USD/JPY {usdjpy_rate:.2f} between 135-142 AND Spread {spread:.2f}% > 2.5%",
        )

    # Default: Moderate risk
    return (
        "MODERATE RISK",
        f"Moderate Risk - USD/JPY {usdjpy_rate:.2f}, Spread {spread:.2f}%",
    )


def plot_ma_cross_analysis(
    df: pd.DataFrame,
    output_filename: str = "ma_cross_analysis.html",
    auto_open: bool = False,
) -> str:
    """
    Create an interactive plot of BTC price with 50D/200D MAs and weekly MAs, cross signals, and spread.

    Features:
    - Top subplot: BTC Price (log), 50D MA, 200D MA, 50W MA, 100W MA, 200W MA, Golden/Death Cross markers.
    - Bottom subplot: MA Spread with structural shading (Bullish/Bearish).
    - Post-Death Cross risk window highlighting.

    Args:
        df: DataFrame with 'date', 'close_price', 'ma_50', 'ma_200', 'ma_350', 'ma_700', 'ma_1400', 'ma_spread', 'golden_cross', 'death_cross'.
        output_filename: Name of the output HTML file (default: "ma_cross_analysis.html")
        auto_open: Whether to automatically open the chart in browser (default: False)

    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data (where MAs exist)
    if "ma_50" not in df.columns or "ma_200" not in df.columns:
        print("⚠ Missing MA columns. Skipping MA Cross chart.")
        return ""

    plot_df = df.dropna(subset=["ma_50", "ma_200"]).copy()

    # Create figure with 2 subplots
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.7, 0.3],
        # Removed subplot titles to save space and use main title
        subplot_titles=None,
    )

    # === TOP SUBPLOT: Price + MAs + Crosses ===

    # 1. Post-Death Cross Highlight (Risk Window)
    # We highlight N days after a death cross
    risk_window_days = 90
    if "death_cross" in plot_df.columns:
        death_cross_dates = plot_df[plot_df["death_cross"]]["date"]

        for date in death_cross_dates:
            end_date = date + pd.Timedelta(days=risk_window_days)
            # Clip end date to max data date
            end_date = min(end_date, plot_df["date"].max())

            fig.add_vrect(
                x0=date,
                x1=end_date,
                fillcolor="red",
                opacity=0.1,
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )

    # 2. BTC Price (Log)
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["close_price"],
            mode="lines",
            name="BTC Price",
            line=dict(color="black", width=1.5),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>Price:</b> $%{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 3. 50D MA
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["ma_50"],
            mode="lines",
            name="50D MA",
            line=dict(color="#2962FF", width=1.5),  # Blue
            hovertemplate="<b>50D MA:</b> $%{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 4. 200D MA
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["ma_200"],
            mode="lines",
            name="200D MA",
            line=dict(color="#D50000", width=1.5),  # Red
            hovertemplate="<b>200D MA:</b> $%{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 5. 50W MA (350 days)
    if "ma_350" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=plot_df["date"],
                y=plot_df["ma_350"],
                mode="lines",
                name="50W MA",
                line=dict(color="#00C853", width=1.5, dash="dot"),  # Green, dotted
                hovertemplate="<b>50W MA:</b> $%{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # 6. 100W MA (700 days)
    if "ma_700" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=plot_df["date"],
                y=plot_df["ma_700"],
                mode="lines",
                name="100W MA",
                line=dict(color="#FF6F00", width=1.5, dash="dash"),  # Orange, dashed
                hovertemplate="<b>100W MA:</b> $%{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # 7. 200W MA (1400 days)
    if "ma_1400" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=plot_df["date"],
                y=plot_df["ma_1400"],
                mode="lines",
                name="200W MA",
                line=dict(
                    color="#9C27B0", width=1.5, dash="dashdot"
                ),  # Purple, dash-dot
                hovertemplate="<b>200W MA:</b> $%{y:,.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # 8. Golden Cross Markers
    if "golden_cross" in plot_df.columns:
        golden_crosses = plot_df[plot_df["golden_cross"]]
        if not golden_crosses.empty:
            fig.add_trace(
                go.Scatter(
                    x=golden_crosses["date"],
                    y=golden_crosses["close_price"],
                    mode="markers",
                    name="Golden Cross",
                    marker=dict(
                        symbol="triangle-up",
                        size=18,
                        color="#00C853",  # Green
                        line=dict(width=1.5, color="black"),
                    ),
                    hovertemplate="<b>Golden Cross!</b><br>Date: %{x|%Y-%m-%d}<br>Price: $%{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    # 6. Death Cross Markers
    if "death_cross" in plot_df.columns:
        death_crosses = plot_df[plot_df["death_cross"]]
        if not death_crosses.empty:
            fig.add_trace(
                go.Scatter(
                    x=death_crosses["date"],
                    y=death_crosses["close_price"],
                    mode="markers",
                    name="Death Cross",
                    marker=dict(
                        symbol="triangle-down",
                        size=18,
                        color="#D50000",  # Red
                        line=dict(width=1.5, color="black"),
                    ),
                    hovertemplate="<b>Death Cross!</b><br>Date: %{x|%Y-%m-%d}<br>Price: $%{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

    # === BOTTOM SUBPLOT: MA Spread ===

    # 7. MA Spread Line
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["ma_spread"],
            mode="lines",
            name="Spread (50D-200D)",
            line=dict(color="#555555", width=1),
            hovertemplate="<b>Spread:</b> $%{y:,.2f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    # Regime Visualization (Background Shading via Fill)
    # Positive Spread (Bullish)
    pos_spread = plot_df["ma_spread"].clip(lower=0)
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=pos_spread,
            mode="none",  # No line, just fill
            fill="tozeroy",
            fillcolor="rgba(76, 175, 80, 0.2)",  # Soft Green
            name="Bullish Regime",
            showlegend=False,
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )

    # Negative Spread (Bearish)
    neg_spread = plot_df["ma_spread"].clip(upper=0)
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=neg_spread,
            mode="none",  # No line, just fill
            fill="tozeroy",
            fillcolor="rgba(244, 67, 54, 0.2)",  # Soft Red
            name="Bearish Regime",
            showlegend=False,
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )

    # Add zero line
    fig.add_hline(y=0, line_width=1, line_color="black", row=2, col=1)

    # === LAYOUT ===
    fig.update_layout(
        title={
            "text": "BTC Death / Golden Cross & MA Spread (BTC Price, log, 50D / 200D MA)"
            "<br><sub>Data Source: Yahoo Finance (BTC-USD)</sub>",
            "x": 0.5,
            "xanchor": "center",
            "y": 0.97,
            "yanchor": "top",
        },
        hovermode="x unified",
        template="plotly_white",
        height=800,
        showlegend=True,
        legend=dict(orientation="h"),
    )

    # Log scale for top plot
    fig.update_yaxes(type="log", title="Price (USD)", row=1, col=1)
    fig.update_yaxes(title="MA Spread (50D − 200D)", row=2, col=1)

    # Range slider on bottom plot
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
    fig.update_xaxes(rangeslider_visible=True, row=2, col=1)


    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)

    print(f"✓ Saved MA Cross chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")

    return str(output_path)


def plot_net_liquidity_dashboard(
    btc_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    output_filename: str = "net_liquidity.html",
    auto_open: bool = False,
) -> str:
    """
    Plot net liquidity and BTC together with major liquidity components.

    Args:
        btc_df: DataFrame with date and close_price columns
        macro_df: DataFrame with net_liquidity_bil and component columns
        output_filename: Output HTML filename
        auto_open: Whether to automatically open chart

    Returns:
        Path to saved chart HTML
    """
    price_df = btc_df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"]).dt.tz_localize(None)

    macro_plot = macro_df.copy()
    macro_plot["date"] = pd.to_datetime(macro_plot["date"]).dt.tz_localize(None)
    macro_plot = macro_plot.sort_values("date")

    required_cols = ["net_liquidity_bil", "walcl_bil", "tga_bil", "rrp_bil"]
    missing_cols = [col for col in required_cols if col not in macro_plot.columns]
    if missing_cols:
        raise ValueError(f"Missing macro columns for liquidity chart: {missing_cols}")

    merged = pd.merge(
        price_df[["date", "close_price"]],
        macro_plot[["date", "net_liquidity_bil", "walcl_bil", "tga_bil", "rrp_bil"]],
        on="date",
        how="left",
    ).sort_values("date")

    for col in ["net_liquidity_bil", "walcl_bil", "tga_bil", "rrp_bil"]:
        merged[col] = merged[col].ffill()

    merged = merged.dropna(subset=["close_price", "net_liquidity_bil"])
    if merged.empty:
        raise ValueError("No overlapping BTC and net liquidity data available")

    merged["net_liquidity_90d_delta"] = merged["net_liquidity_bil"].diff(90)
    latest = merged.iloc[-1]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.56, 0.44],
        specs=[[{}], [{"secondary_y": True}]],
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["net_liquidity_bil"],
            mode="lines",
            name="Net Liquidity (bn)",
            showlegend=True,
            line=dict(color="#1f77b4", width=2.5),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Net Liquidity: %{y:,.0f} bn<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["walcl_bil"],
            mode="lines",
            name="Fed Assets",
            showlegend=True,
            line=dict(color="#2ca02c", width=1.6),
            opacity=0.75,
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>WALCL: %{y:,.0f} bn<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["tga_bil"],
            mode="lines",
            name="TGA",
            showlegend=True,
            line=dict(color="#ff7f0e", width=1.4, dash="dot"),
            opacity=0.9,
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>TGA: %{y:,.0f} bn<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["rrp_bil"],
            mode="lines",
            name="ON RRP",
            showlegend=True,
            line=dict(color="#d62728", width=1.4, dash="dash"),
            opacity=0.9,
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>ON RRP: %{y:,.0f} bn<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=merged["date"],
            y=merged["net_liquidity_90d_delta"],
            name="90D Change",
            showlegend=True,
            marker_color=np.where(
                merged["net_liquidity_90d_delta"] >= 0,
                "rgba(40, 167, 69, 0.55)",
                "rgba(220, 53, 69, 0.55)",
            ),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>90D Change: %{y:,.0f} bn<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["close_price"],
            mode="lines",
            name="BTC Price",
            showlegend=True,
            line=dict(color="#111111", width=2.1),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BTC: $%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    fig.add_hline(
        y=0,
        line_color="rgba(80, 80, 80, 0.5)",
        line_dash="dot",
        row=2,
        col=1,
        secondary_y=False,
    )

    fig.update_layout(
        title={
            "text": (
                "BTC vs Net Liquidity Dashboard"
                f"<br><sub>Latest Net Liquidity: {latest['net_liquidity_bil']:,.0f} bn | "
                f"90D Change: {latest['net_liquidity_90d_delta']:,.0f} bn</sub>"
            ),
            "x": 0.5,
            "xanchor": "center",
            "y": 0.97,
            "yanchor": "top",
        },
        template="plotly_white",
        hovermode="x unified",
        height=820,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.06,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor="rgba(0, 0, 0, 0.15)",
            borderwidth=1,
            itemsizing="constant",
            entrywidthmode="fraction",
            entrywidth=0.30,
            font=dict(size=11),
        ),
        margin=dict(l=70, r=70, t=210, b=70),
    )

    fig.update_yaxes(title_text="USD Billion", row=1, col=1)
    fig.update_yaxes(title_text="90D Delta (bn USD)", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="BTC Price (USD, log)", type="log", row=2, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Date", row=2, col=1, rangeslider_visible=True)

    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)
    add_info_modal_script(
        output_path,
        title="How to Read: Net Liquidity",
        content_html=(
            "<h4>What this chart measures</h4>"
            "<p><b>Net Liquidity</b> = Fed Assets (WALCL) - TGA (WTREGEN) - ON RRP (RRPONTSYD).</p>"
            "<p>It is a practical proxy for how much system cash is available to absorb risk.</p>"
            "<h4>How to interpret</h4>"
            "<p>If net liquidity trends down, macro conditions are tightening; BTC usually faces stronger headwinds.</p>"
            "<p><b>90D Change bars</b>: green means liquidity improving, red means liquidity draining.</p>"
            "<h4>Quick use</h4>"
            "<p>Use this panel as the background regime filter, not a single-day trading trigger.</p>"
        ),
    )

    print(f"✓ Saved net liquidity dashboard to: {output_path}")
    return str(output_path)


def plot_funding_credit_stress(
    btc_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    output_filename: str = "funding_credit_stress.html",
    auto_open: bool = False,
) -> str:
    """
    Plot funding and credit stress signals alongside BTC price.

    Args:
        btc_df: DataFrame with date and close_price columns
        macro_df: DataFrame with sofr, move, and hy_oas columns
        output_filename: Output HTML filename
        auto_open: Whether to open chart automatically

    Returns:
        Path to saved chart HTML
    """
    price_df = btc_df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"]).dt.tz_localize(None)

    macro_plot = macro_df.copy()
    macro_plot["date"] = pd.to_datetime(macro_plot["date"]).dt.tz_localize(None)
    macro_plot = macro_plot.sort_values("date")

    required_cols = ["sofr", "move", "hy_oas"]
    missing_cols = [col for col in required_cols if col not in macro_plot.columns]
    if missing_cols:
        raise ValueError(f"Missing macro columns for stress chart: {missing_cols}")

    merged = pd.merge(
        price_df[["date", "close_price"]],
        macro_plot[["date", "sofr", "move", "hy_oas"]],
        on="date",
        how="left",
    ).sort_values("date")

    for col in ["sofr", "move", "hy_oas"]:
        merged[col] = merged[col].ffill()

    merged = merged.dropna(subset=["close_price", "sofr", "hy_oas"])
    if merged.empty:
        raise ValueError("No overlapping BTC and stress indicator data available")

    latest = merged.iloc[-1]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        row_heights=[0.5, 0.5],
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["sofr"],
            mode="lines",
            name="SOFR",
            showlegend=True,
            line=dict(color="#1f77b4", width=2.2),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>SOFR: %{y:.2f}%<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["move"],
            mode="lines",
            name="MOVE",
            showlegend=True,
            line=dict(color="#ff7f0e", width=2.0, dash="dash"),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>MOVE: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["hy_oas"],
            mode="lines",
            name="HY OAS",
            showlegend=True,
            line=dict(color="#d62728", width=2.2),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>HY OAS: %{y:.2f}%<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["close_price"],
            mode="lines",
            name="BTC Price",
            showlegend=True,
            line=dict(color="#111111", width=2.0),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BTC: $%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    fig.add_hline(
        y=5.0,
        line_color="rgba(220, 53, 69, 0.7)",
        line_dash="dot",
        annotation_text="HY OAS 5% stress threshold",
        annotation_position="top left",
        row=2,
        col=1,
        secondary_y=False,
    )

    fig.update_layout(
        title={
            "text": (
                "Funding & Credit Stress Monitor"
                f"<br><sub>Latest SOFR: {latest['sofr']:.2f}% | MOVE: {latest['move']:.1f} | HY OAS: {latest['hy_oas']:.2f}%</sub>"
            ),
            "x": 0.5,
            "xanchor": "center",
            "y": 0.97,
            "yanchor": "top",
        },
        template="plotly_white",
        hovermode="x unified",
        height=820,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.06,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(255, 255, 255, 0.9)",
            bordercolor="rgba(0, 0, 0, 0.15)",
            borderwidth=1,
            itemsizing="constant",
            entrywidthmode="fraction",
            entrywidth=0.22,
            font=dict(size=11),
        ),
        margin=dict(l=70, r=70, t=170, b=70),
    )

    fig.update_yaxes(title_text="SOFR (%)", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="MOVE", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="HY OAS (%)", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="BTC Price (USD, log)", type="log", row=2, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Date", row=2, col=1, rangeslider_visible=True)

    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)
    add_info_modal_script(
        output_path,
        title="How to Read: Funding & Credit Stress",
        content_html=(
            "<h4>Signals in this panel</h4>"
            "<p><b>SOFR</b>: short-term funding cost. Rising SOFR means money is getting more expensive.</p>"
            "<p><b>MOVE</b>: U.S. rate volatility. Rising MOVE means bond market stress and weaker risk tolerance.</p>"
            "<p><b>HY OAS</b>: high-yield credit spread. Widening spread means financing stress is spreading.</p>"
            "<h4>Rule of thumb</h4>"
            "<p>When SOFR + MOVE + HY OAS rise together, BTC drawdown risk usually increases.</p>"
        ),
    )

    print(f"✓ Saved funding/credit stress chart to: {output_path}")
    return str(output_path)


MACRO_COMPONENTS = ["net_liquidity_bil", "sofr", "move", "hy_oas"]


def compute_macro_risk_frame(btc_df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    """Daily macro risk score on BTC price dates, with forward BTC returns.

    Components are ranked on a daily calendar covering all macro history (not
    just the BTC price range), each day only among values known up to that day,
    so the score history and its validation never use later data.
    """
    price = btc_df[["date", "close_price"]].copy()
    price["date"] = pd.to_datetime(price["date"]).dt.tz_localize(None)
    macro = macro_df.copy()
    macro["date"] = pd.to_datetime(macro["date"]).dt.tz_localize(None)
    missing_cols = [col for col in MACRO_COMPONENTS if col not in macro.columns]
    if missing_cols:
        raise ValueError(f"Missing macro columns for risk score chart: {missing_cols}")
    macro = macro[["date", *MACRO_COMPONENTS]].sort_values("date")

    start = min(price["date"].min(), macro["date"].min())
    end = max(price["date"].max(), macro["date"].max())
    frame = (
        pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
        .merge(macro, on="date", how="left")
        .merge(price, on="date", how="left")
    )
    for col in MACRO_COMPONENTS:
        frame[col] = frame[col].ffill()

    frame["net_liquidity_90d_change"] = frame["net_liquidity_bil"].diff(90)
    # Higher rank = higher risk
    frame["risk_net_liq"] = 1.0 - known_rank(frame["net_liquidity_90d_change"], MACRO_RANK_MIN_HISTORY)
    frame["risk_sofr"] = known_rank(frame["sofr"], MACRO_RANK_MIN_HISTORY)
    frame["risk_move"] = known_rank(frame["move"], MACRO_RANK_MIN_HISTORY)
    frame["risk_hy_oas"] = known_rank(frame["hy_oas"], MACRO_RANK_MIN_HISTORY)
    frame["macro_risk_score"] = 100.0 * (
        MACRO_RISK_SCORE_WEIGHTS["net_liquidity_90d_change"] * frame["risk_net_liq"]
        + MACRO_RISK_SCORE_WEIGHTS["sofr"] * frame["risk_sofr"]
        + MACRO_RISK_SCORE_WEIGHTS["move"] * frame["risk_move"]
        + MACRO_RISK_SCORE_WEIGHTS["hy_oas"] * frame["risk_hy_oas"]
    )

    merged = frame.dropna(subset=["close_price"]).reset_index(drop=True)
    merged["fwd_7d_return_pct"] = (merged["close_price"].shift(-7) / merged["close_price"] - 1.0) * 100.0
    merged["fwd_30d_return_pct"] = (merged["close_price"].shift(-30) / merged["close_price"] - 1.0) * 100.0
    return merged


def plot_macro_risk_score(
    btc_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    output_filename: str = "macro_risk_score.html",
    auto_open: bool = False,
) -> str:
    """
    Plot a composite macro risk score and validate it against forward BTC returns.

    The score blends:
        - Net liquidity 90D change (decline is riskier)
        - SOFR level
        - MOVE level
        - HY OAS level
    """
    merged = compute_macro_risk_frame(btc_df, macro_df)
    merged = merged.dropna(subset=["macro_risk_score", "close_price", "fwd_30d_return_pct"])

    if merged.empty:
        raise ValueError("No overlapping data available for macro risk score chart")

    high_risk_mask = merged["macro_risk_score"] >= 70
    low_risk_mask = merged["macro_risk_score"] <= 30

    high_count = int(high_risk_mask.sum())
    low_count = int(low_risk_mask.sum())
    hit_rate = (
        float((merged.loc[high_risk_mask, "fwd_30d_return_pct"] < 0).mean() * 100.0)
        if high_count > 0
        else float("nan")
    )
    high_avg = (
        float(merged.loc[high_risk_mask, "fwd_30d_return_pct"].mean())
        if high_count > 0
        else float("nan")
    )
    low_avg = (
        float(merged.loc[low_risk_mask, "fwd_30d_return_pct"].mean())
        if low_count > 0
        else float("nan")
    )
    if (
        merged["macro_risk_score"].nunique() > 1
        and merged["fwd_30d_return_pct"].nunique() > 1
    ):
        corr = float(merged["macro_risk_score"].corr(merged["fwd_30d_return_pct"]))
    else:
        corr = float("nan")

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        row_heights=[0.34, 0.36, 0.30],
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["macro_risk_score"],
            mode="lines",
            name="Macro Risk Score",
            line=dict(color="#8c2d04", width=2.4),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Risk Score: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_hline(y=70, line_color="#d62728", line_dash="dash", row=1, col=1)
    fig.add_hline(y=30, line_color="#2ca02c", line_dash="dash", row=1, col=1)

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["close_price"],
            mode="lines",
            name="BTC Price",
            line=dict(color="#111111", width=2.1),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BTC: $%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["fwd_30d_return_pct"],
            mode="lines",
            name="Forward 30D Return",
            line=dict(color="#1f77b4", width=2.0),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Fwd 30D: %{y:.2f}%<extra></extra>",
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=merged["date"],
            y=merged["fwd_7d_return_pct"],
            mode="lines",
            name="Forward 7D Return",
            line=dict(color="#ff7f0e", width=1.4, dash="dot"),
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Fwd 7D: %{y:.2f}%<extra></extra>",
        ),
        row=3,
        col=1,
    )

    fig.add_hline(y=0, line_color="rgba(80,80,80,0.5)", line_dash="dot", row=3, col=1)

    # Highlight high-risk windows on all panels.
    in_window = False
    start_dt = None
    for _, r in merged.iterrows():
        is_high = bool(r["macro_risk_score"] >= 70)
        if is_high and not in_window:
            in_window = True
            start_dt = r["date"]
        elif (not is_high) and in_window:
            in_window = False
            end_dt = r["date"]
            fig.add_vrect(x0=start_dt, x1=end_dt, fillcolor="rgba(220,53,69,0.08)", line_width=0)
    if in_window and start_dt is not None:
        fig.add_vrect(
            x0=start_dt,
            x1=merged["date"].iloc[-1],
            fillcolor="rgba(220,53,69,0.08)",
            line_width=0,
        )

    corr_text = f"{corr:.2f}" if np.isfinite(corr) else "N/A"
    hit_rate_text = f"{hit_rate:.1f}%" if np.isfinite(hit_rate) else "N/A"
    high_avg_text = f"{high_avg:.2f}%" if np.isfinite(high_avg) else "N/A"
    low_avg_text = f"{low_avg:.2f}%" if np.isfinite(low_avg) else "N/A"
    weights_text = (
        f"NetLiq {MACRO_RISK_SCORE_WEIGHTS['net_liquidity_90d_change']:.2f}, "
        f"SOFR {MACRO_RISK_SCORE_WEIGHTS['sofr']:.2f}, "
        f"MOVE {MACRO_RISK_SCORE_WEIGHTS['move']:.2f}, "
        f"HY OAS {MACRO_RISK_SCORE_WEIGHTS['hy_oas']:.2f}"
    )

    fig.update_layout(
        title={
            "text": (
                "Macro Risk Score Validation"
                f"<br><sub>Corr(score, fwd30d)={corr_text} | "
                f"High-risk hit rate={hit_rate_text} | "
                f"Avg fwd30d (high/low)={high_avg_text} / {low_avg_text}</sub>"
                f"<br><sub>Default Weights: {weights_text}</sub>"
            ),
            "x": 0.5,
            "xanchor": "center",
            "y": 0.97,
            "yanchor": "top",
        },
        template="plotly_white",
        hovermode="x unified",
        height=900,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.04,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="rgba(0,0,0,0.15)",
            borderwidth=1,
            font=dict(size=11),
            entrywidthmode="fraction",
            entrywidth=0.22,
        ),
        margin=dict(l=70, r=70, t=180, b=70),
    )

    fig.update_yaxes(title_text="Risk Score (0-100)", range=[0, 100], row=1, col=1)
    fig.update_yaxes(title_text="BTC Price (USD, log)", type="log", row=2, col=1)
    fig.update_yaxes(title_text="Forward Return (%)", row=3, col=1)
    fig.update_xaxes(title_text="Date", row=3, col=1, rangeslider_visible=True)

    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    write_chart_html(fig, output_path, auto_open=auto_open)
    add_info_modal_script(
        output_path,
        title="How to Read: Macro Risk Score",
        content_html=(
            "<h4>Score meaning</h4>"
            "<p><b>Score >= 70</b>: high macro risk regime.<br><b>Score <= 30</b>: low macro risk regime.</p>"
            "<p>The score combines four components: net liquidity change, SOFR, MOVE, and HY OAS.</p>"
            f"<p><b>Default weights</b>: NetLiq {MACRO_RISK_SCORE_WEIGHTS['net_liquidity_90d_change']:.2f}, "
            f"SOFR {MACRO_RISK_SCORE_WEIGHTS['sofr']:.2f}, MOVE {MACRO_RISK_SCORE_WEIGHTS['move']:.2f}, "
            f"HY OAS {MACRO_RISK_SCORE_WEIGHTS['hy_oas']:.2f}.</p>"
            "<h4>Validation panel</h4>"
            "<p>Bottom panel plots forward BTC returns (7D/30D) to check if high score periods"
            " are followed by weaker performance.</p>"
            "<p>To tune quickly, edit <code>MACRO_RISK_SCORE_WEIGHTS</code> in <code>visualization.py</code> and regenerate.</p>"
        ),
    )

    print(f"✓ Saved macro risk score chart to: {output_path}")
    return str(output_path)


def generate_all_charts(df: pd.DataFrame, auto_open: bool = True) -> dict:
    """
    Generate all visualization charts at once.

    Args:
        df: DataFrame with complete valuation metrics
        auto_open: Whether to automatically open the main chart in browser

    Returns:
        Dictionary mapping chart names to file paths
    """
    print("\n" + "=" * 80)
    print("GENERATING INTERACTIVE CHARTS")
    print("=" * 80)

    charts = {}

    # Main valuation ratios chart (auto-open this one)
    print("\n1. Valuation Ratios Chart...")
    charts["ratios"] = plot_valuation_ratios(df, auto_open=auto_open)

    # Price comparison chart
    print("\n2. Price Comparison Chart...")
    charts["price_comparison"] = plot_price_comparison(df, auto_open=False)

    # MA Cross Analysis chart
    print("\n3. MA Cross Analysis Chart...")
    charts["ma_cross"] = plot_ma_cross_analysis(df, auto_open=False)

    print("\n" + "=" * 80)
    print("✓ All charts generated successfully!")
    print("=" * 80)
    print(f"\nCharts saved in: {get_output_dir()}")
    print("\nTo view charts:")
    for name, path in charts.items():
        print(f"  - {name}: {Path(path).name}")

    return charts


if __name__ == "__main__":
    # Quick test
    print("Testing visualization module...")
    print(f"Charts directory: {get_output_dir()}")


def create_futures_oi_timeseries_chart(
    btc_df: pd.DataFrame, oi_df: pd.DataFrame, output_path: str
) -> None:
    """
    Create a professional Bloomberg-style chart:
    Row 1: BTC Price (log) vs 200-day MA with regime backgrounds
    Row 2: Futures Open Interest (USD) with risk zones

    Args:
        btc_df: DataFrame with 'close_price' and date index.
        oi_df: DataFrame with 'oi_usd' and date index.
        output_path: HTML output file path.
    """
    # Ensure indices are datetime
    if not isinstance(btc_df.index, pd.DatetimeIndex):
        btc_df.index = pd.to_datetime(btc_df.index)
    if not isinstance(oi_df.index, pd.DatetimeIndex):
        oi_df.index = pd.to_datetime(oi_df.index)

    # Time range alignment
    start_date = max(btc_df.index.min(), oi_df.index.min())
    end_date = min(btc_df.index.max(), oi_df.index.max())

    btc_plot = btc_df.loc[start_date:end_date].copy()
    oi_plot = oi_df.loc[start_date:end_date].copy()

    if btc_plot.empty or oi_plot.empty:
        print("⚠ No overlapping data found for Futures OI chart.")
        return

    # Calculate 200-day MA
    if "ma200" not in btc_plot.columns:
        btc_df["ma200"] = btc_df["close_price"].rolling(window=200).mean()
        btc_plot["ma200"] = btc_df.loc[start_date:end_date, "ma200"]

    # Create subplots with NO subplot titles (we'll use a unified title)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.58, 0.42],
        subplot_titles=None,
    )

    # ===== ROW 1: PRICE PANEL WITH REGIME BACKGROUNDS =====

    # Add regime background fills (price > MA = bullish, price < MA = bearish)
    price_above_ma = btc_plot["close_price"] > btc_plot["ma200"]

    # Create segments for background coloring
    for i in range(1, len(btc_plot)):
        if pd.notna(btc_plot["ma200"].iloc[i]):
            color = (
                "rgba(144, 238, 144, 0.12)"
                if price_above_ma.iloc[i]
                else "rgba(255, 182, 193, 0.12)"
            )
            fig.add_vrect(
                x0=btc_plot.index[i - 1],
                x1=btc_plot.index[i],
                fillcolor=color,
                line_width=0,
                layer="below",
                row=1,
                col=1,
            )

    # BTC Price line
    fig.add_trace(
        go.Scatter(
            x=btc_plot.index,
            y=btc_plot["close_price"],
            name="BTC Price",
            line=dict(color="#1a1a1a", width=1.8),
            hovertemplate="$%{y:,.0f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # 200D MA line (BLUE DASHED - restored)
    fig.add_trace(
        go.Scatter(
            x=btc_plot.index,
            y=btc_plot["ma200"],
            name="200D MA",
            line=dict(color="#2962FF", width=1.5, dash="dash"),  # DASHED line
            hovertemplate="$%{y:,.0f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.update_yaxes(
        type="log",
        title_text=None,  # Remove axis title for cleaner look
        tickformat="$,.0f",
        nticks=8,  # Request more ticks on log scale
        row=1,
        col=1,
        showgrid=True,
        gridcolor="#f0f0f0",
    )

    # ===== ROW 2: OI PANEL =====

    fig.add_trace(
        go.Scatter(
            x=oi_plot.index,
            y=oi_plot["oi_usd"],
            name="OI (USD)",
            line=dict(color="#DAA520", width=1.8),
            fill="tozeroy",
            fillcolor="rgba(218, 165, 32, 0.08)",
            hovertemplate="$%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )

    # Set Y-axis range based on actual data range to show fluctuations clearly
    # This is best practice: don't start from 0 when data has small relative changes
    if not oi_plot.empty:
        oi_values = oi_plot["oi_usd"].dropna()
        if not oi_values.empty:
            oi_min = oi_values.min()
            oi_max = oi_values.max()
            oi_range = oi_max - oi_min
            # Add 5% padding above and below for better visualization
            y_min = max(0, oi_min - oi_range * 0.05)
            y_max = oi_max + oi_range * 0.05
        else:
            y_min = None
            y_max = None
    else:
        y_min = None
        y_max = None

    # Y-axis configuration: let Plotly auto-handle ticks to prevent duplicates
    fig.update_yaxes(
        title_text=None,
        tickformat="$,.2s",  # Use 2 decimal places for better precision (e.g., $750M, $775M, $800M)
        range=[y_min, y_max] if y_min is not None and y_max is not None else None,
        row=2,
        col=1,
        showgrid=True,
        gridcolor="#f0f0f0",
        tickmode="auto",  # Let Plotly automatically space ticks
    )

    # Risk Zones
    if not oi_plot.empty:
        oi_values = oi_plot["oi_usd"].dropna()
        if not oi_values.empty:
            top_10 = oi_values.quantile(0.90)
            bottom_10 = oi_values.quantile(0.10)

            # High OI Zone (risk)
            fig.add_hrect(
                y0=top_10,
                y1=oi_values.max() * 1.5,
                fillcolor="rgba(220, 53, 69, 0.08)",
                line_width=0,
                row=2,
                col=1,
            )
            fig.add_annotation(
                x=end_date,
                y=top_10,
                text="High Leverage",
                showarrow=False,
                yshift=8,
                xanchor="right",
                font=dict(size=9, color="#dc3545"),
                row=2,
                col=1,
            )

            # Low OI Zone (clean)
            fig.add_hrect(
                y0=0,
                y1=bottom_10,
                fillcolor="rgba(40, 167, 69, 0.08)",
                line_width=0,
                row=2,
                col=1,
            )
            fig.add_annotation(
                x=end_date,
                y=bottom_10,
                text="Deleveraged",
                showarrow=False,
                yshift=-8,
                xanchor="right",
                font=dict(size=9, color="#28a745"),
                row=2,
                col=1,
            )

    # ===== UNIFIED TITLE BLOCK WITH LEGEND =====
    title_text = (
        "<b style='font-size:16px'>BTC Price (log) & Futures Open Interest (USD)</b><br>"
        + "<span style='font-size:11px; color:#666'>Price Trend Regime (Price vs 200D MA)</span>"
    )

    fig.update_layout(
        title=dict(
            text=title_text,
            y=0.98,
            x=0.5,
            xanchor="center",
            yanchor="top",
        ),
        template="plotly_white",
        height=620,
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h"),
        plot_bgcolor="white",
    )
    # Added (not set via update_layout) so the zone labels above are kept
    fig.add_annotation(
        text="Data: Binance",
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.01,
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        font=dict(size=8, color="#999"),
        opacity=0.6,
    )

    fig.update_xaxes(rangeslider_visible=False, row=2, col=1)
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="#f0f0f0")

    # Save
    output_file = Path(output_path)
    write_chart_html(fig, output_file)

    print(f"✓ Saved Futures OI chart to: {output_file.resolve()}")


def create_oi_quadrant_chart(
    btc_df: pd.DataFrame, oi_df: pd.DataFrame, output_path: str, lookback_days: int = 5
) -> None:
    """
    Create a professional 4-quadrant chart: Price Change vs OI Change.

    Args:
        btc_df: DataFrame with 'close_price'.
        oi_df: DataFrame with 'oi_usd'.
        output_path: HTML output file path.
        lookback_days: Window for calculating percentage change.
    """
    # Ensure indices are datetime
    if not isinstance(btc_df.index, pd.DatetimeIndex):
        btc_df.index = pd.to_datetime(btc_df.index)
    if not isinstance(oi_df.index, pd.DatetimeIndex):
        oi_df.index = pd.to_datetime(oi_df.index)

    # Align data
    start_date = max(btc_df.index.min(), oi_df.index.min())
    end_date = min(btc_df.index.max(), oi_df.index.max())

    btc_aligned = btc_df.loc[start_date:end_date]["close_price"]
    oi_aligned = oi_df.loc[start_date:end_date]["oi_usd"]

    # Calculate % Change
    btc_pct = btc_aligned.pct_change(lookback_days) * 100
    oi_pct = oi_aligned.pct_change(lookback_days) * 100

    # Combine into one DF
    df = pd.DataFrame({"price_chg": btc_pct, "oi_chg": oi_pct}).dropna()

    if df.empty:
        print("⚠ Not enough data for Quadrant chart.")
        return

    # Get recent history (trail) and today
    trail_len = 20
    recent_df = df.iloc[-trail_len:]
    today = df.iloc[-1]

    # Determine Current Mode
    p_chg = today["price_chg"]
    o_chg = today["oi_chg"]

    if p_chg > 0 and o_chg > 0:
        mode_label = "Risky Up (leveraged)"
        mode_color = "#ff8800"  # Orange
    elif p_chg > 0 and o_chg < 0:
        mode_label = "Healthy Up (spot-led)"
        mode_color = "#28a745"  # Green
    elif p_chg < 0 and o_chg > 0:
        mode_label = "Squeeze Setup (crowded)"
        mode_color = "#ffc107"  # Yellow
    elif p_chg < 0 and o_chg < 0:
        mode_label = "Flush-Out (deleveraging)"
        mode_color = "#6c757d"  # Grey
    else:
        mode_label = "Neutral"
        mode_color = "#888"

    # Create Figure
    fig = go.Figure()

    # Determine axis limits for backgrounds
    price_max = max(
        abs(recent_df["price_chg"].max()), abs(recent_df["price_chg"].min()), 5
    )
    oi_max = max(abs(recent_df["oi_chg"].max()), abs(recent_df["oi_chg"].min()), 5)

    # ===== QUADRANT BACKGROUNDS (trader-friendly semantic colors) =====

    # Price ↑, OI ↑ (top-right): Risky Up - soft red/orange
    fig.add_shape(
        type="rect",
        x0=0,
        x1=price_max * 1.1,
        y0=0,
        y1=oi_max * 1.1,
        fillcolor="rgba(255, 99, 71, 0.08)",
        line_width=0,
        layer="below",
    )

    # Price ↑, OI ↓ (bottom-right): Healthy Up - soft green
    fig.add_shape(
        type="rect",
        x0=0,
        x1=price_max * 1.1,
        y0=-oi_max * 1.1,
        y1=0,
        fillcolor="rgba(40, 167, 69, 0.08)",
        line_width=0,
        layer="below",
    )

    # Price ↓, OI ↑ (top-left): Squeeze Setup - soft yellow
    fig.add_shape(
        type="rect",
        x0=-price_max * 1.1,
        x1=0,
        y0=0,
        y1=oi_max * 1.1,
        fillcolor="rgba(255, 193, 7, 0.10)",
        line_width=0,
        layer="below",
    )

    # Price ↓, OI ↓ (bottom-left): Flush-Out - soft blue-grey
    fig.add_shape(
        type="rect",
        x0=-price_max * 1.1,
        x1=0,
        y0=-oi_max * 1.1,
        y1=0,
        fillcolor="rgba(108, 117, 125, 0.08)",
        line_width=0,
        layer="below",
    )

    # Quadrant lines
    fig.add_hline(y=0, line_color="#999", line_width=1.5)
    fig.add_vline(x=0, line_color="#999", line_width=1.5)

    # ===== QUADRANT LABELS (short text inside each quadrant) =====
    label_offset_x = price_max * 0.7
    label_offset_y = oi_max * 0.7

    quadrant_labels = [
        (
            label_offset_x,
            label_offset_y,
            "Risky Up",
            "#FF6347",
        ),  # top-right, red/orange
        (
            label_offset_x,
            -label_offset_y,
            "Healthy Up",
            "#28a745",
        ),  # bottom-right, green
        (
            -label_offset_x,
            label_offset_y,
            "Squeeze\nSetup",
            "#FFC107",
        ),  # top-left, yellow
        (-label_offset_x, -label_offset_y, "Flush-Out", "#6c757d"),  # bottom-left, grey
    ]

    for x, y, text, color in quadrant_labels:
        fig.add_annotation(
            x=x,
            y=y,
            text=text,
            showarrow=False,
            font=dict(size=10, color=color),
            opacity=0.5,
        )

    # ===== HISTORICAL TRAIL =====
    fig.add_trace(
        go.Scatter(
            x=recent_df["price_chg"],
            y=recent_df["oi_chg"],
            mode="lines+markers",
            name="Trail",
            line=dict(color="#ccc", width=1, dash="dot"),
            marker=dict(size=3, color="#bbb", opacity=0.4),
            hovertemplate="<b>%{hovertext}</b><br>"
            + "Price Change: %{x:.1f}%<br>"
            + "OI Change: %{y:.1f}%<extra></extra>",
            hovertext=recent_df.index.strftime("%Y-%m-%d"),
            showlegend=False,
        )
    )

    # ===== TODAY'S MARKER (large, with outline) =====
    fig.add_trace(
        go.Scatter(
            x=[today["price_chg"]],
            y=[today["oi_chg"]],
            mode="markers",
            name="Current",
            marker=dict(size=16, color=mode_color, line=dict(width=2, color="white")),
            hovertemplate=f"<b>{today.name.strftime('%Y-%m-%d')}</b><br>"
            + "Price: %{x:.1f}%<br>"
            + "OI: %{y:.1f}%<br>"
            + f"{mode_label}<extra></extra>",
            showlegend=False,
        )
    )

    # ===== DATA SOURCE LABEL =====
    data_source_text = "Data: Binance"

    # ===== LAYOUT =====
    title_text = (
        f"<b style='font-size:15px'>Price vs OI Change ({lookback_days}-Day)</b>"
    )

    fig.update_layout(
        title=dict(
            text=title_text,
            y=0.97,
            x=0.5,
            xanchor="center",
            yanchor="top",
            font=dict(size=15),
        ),
        xaxis=dict(
            title=None,
            tickformat=".0f%",
            showgrid=True,
            gridcolor="#f5f5f5",
            zeroline=False,
        ),
        yaxis=dict(
            title=None,
            tickformat=".0f%",
            showgrid=True,
            gridcolor="#f5f5f5",
            zeroline=False,
        ),
        annotations=[
            # Data source label (bottom-right)
            dict(
                text=data_source_text,
                xref="paper",
                yref="paper",
                x=0.99,
                y=0.01,
                xanchor="right",
                yanchor="bottom",
                showarrow=False,
                font=dict(size=8, color="#999"),
                opacity=0.6,
            )
        ],
        template="plotly_white",
        height=460,
        width=460,
        showlegend=False,
        margin=dict(l=50, r=40, t=80, b=50),
        plot_bgcolor="white",
    )

    # Save
    output_file = Path(output_path)
    write_chart_html(fig, output_file)

    # Also save current quadrant info to a JSON file for HTML to read
    quadrant_info = {
        "current_quadrant": mode_label,
        "price_change": float(p_chg),
        "oi_change": float(o_chg),
        "quadrant_id": None,  # Will be set based on conditions
    }

    # Determine quadrant ID for HTML highlighting
    if p_chg > 0 and o_chg > 0:
        quadrant_info["quadrant_id"] = "q1"  # Top-right
    elif p_chg > 0 and o_chg < 0:
        quadrant_info["quadrant_id"] = "q2"  # Bottom-right
    elif p_chg < 0 and o_chg > 0:
        quadrant_info["quadrant_id"] = "q3"  # Top-left
    elif p_chg < 0 and o_chg < 0:
        quadrant_info["quadrant_id"] = "q4"  # Bottom-left

    info_file = output_file.parent / "oi_quadrant_info.json"
    _atomic_write_text(info_file, json.dumps(quadrant_info, indent=2))

    print(f"✓ Saved OI Quadrant chart to: {output_file.resolve()}")
    print(f"✓ Saved quadrant info to: {info_file.resolve()}")
