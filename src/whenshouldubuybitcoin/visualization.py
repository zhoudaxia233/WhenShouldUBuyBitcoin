"""
Visualization module for Bitcoin valuation analysis.

This module provides interactive charts using Plotly to visualize:
- DCA and Trend ratios over time
- Double undervaluation zones
- Price vs fair value comparisons
"""

from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


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


def plot_valuation_ratios(
    df: pd.DataFrame,
    output_filename: str = "valuation_ratios.html",
    auto_open: bool = True
) -> str:
    """
    Create an interactive plot of valuation ratios with double undervaluation zones highlighted.
    
    This plot shows:
    - ratio_dca (Price/DCA) over time
    - ratio_trend (Price/Trend) over time
    - Horizontal line at y=1.0 (fair value threshold)
    - Shaded regions where both ratios < 1.0 (buy zones)
    
    Args:
        df: DataFrame with date, ratio_dca, ratio_trend, and is_double_undervalued columns
        output_filename: Name of the output HTML file (default: "valuation_ratios.html")
        auto_open: Whether to automatically open the chart in browser (default: True)
        
    Returns:
        Path to the saved HTML file
    """
    # Filter to valid data (where metrics exist)
    plot_df = df.dropna(subset=["ratio_dca", "ratio_trend"]).copy()
    
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
    fig.add_trace(go.Scatter(
        x=plot_df["date"],
        y=plot_df["ratio_dca"],
        mode="lines",
        name="Price/DCA Ratio",
        line=dict(color="rgb(31, 119, 180)", width=2),
        hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                      "<b>Price/DCA:</b> %{y:.3f}<br>" +
                      "<extra></extra>"
    ))
    
    # Add ratio_trend line
    fig.add_trace(go.Scatter(
        x=plot_df["date"],
        y=plot_df["ratio_trend"],
        mode="lines",
        name="Price/Trend Ratio",
        line=dict(color="rgb(44, 160, 44)", width=2),
        hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                      "<b>Price/Trend:</b> %{y:.3f}<br>" +
                      "<extra></extra>"
    ))
    
    # Add horizontal line at y=1.0 (fair value threshold)
    fig.add_hline(
        y=1.0,
        line_dash="dash",
        line_color="red",
        line_width=2,
        annotation_text="Fair Value (ratio = 1.0)",
        annotation_position="right"
    )
    
    # Update layout
    fig.update_layout(
        title={
            "text": "Bitcoin Valuation Ratios Over Time<br><sub>Red shaded areas = Double Undervaluation Buy Zones</sub>",
            "x": 0.5,
            "xanchor": "center"
        },
        xaxis_title="Date",
        yaxis_title="Ratio (Price / Fair Value)",
        hovermode="x unified",
        template="plotly_white",
        height=600,
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)"
        )
    )
    
    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=2, label="2Y", step="year", stepmode="backward"),
                dict(step="all", label="All")
            ])
        )
    )
    
    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    fig.write_html(str(output_path), auto_open=auto_open)
    
    print(f"✓ Saved interactive chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")
    
    return str(output_path)


def plot_price_comparison(
    df: pd.DataFrame,
    output_filename: str = "price_comparison.html",
    auto_open: bool = False
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
    fig.add_trace(go.Scatter(
        x=plot_df["date"],
        y=plot_df["close_price"],
        mode="lines",
        name="Actual Price",
        line=dict(color="black", width=2),
        hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                      "<b>Price:</b> $%{y:,.2f}<br>" +
                      "<extra></extra>"
    ))
    
    # Add DCA cost
    fig.add_trace(go.Scatter(
        x=plot_df["date"],
        y=plot_df["dca_cost"],
        mode="lines",
        name="200-day DCA Cost",
        line=dict(color="rgb(31, 119, 180)", width=2, dash="dash"),
        hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                      "<b>DCA Cost:</b> $%{y:,.2f}<br>" +
                      "<extra></extra>"
    ))
    
    # Add trend value
    fig.add_trace(go.Scatter(
        x=plot_df["date"],
        y=plot_df["trend_value"],
        mode="lines",
        name="Power Law Trend",
        line=dict(color="rgb(44, 160, 44)", width=2, dash="dot"),
        hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                      "<b>Trend:</b> $%{y:,.2f}<br>" +
                      "<extra></extra>"
    ))
    
    # Highlight double undervaluation zones
    double_uv_df = plot_df[plot_df["is_double_undervalued"]].copy()
    if not double_uv_df.empty:
        fig.add_trace(go.Scatter(
            x=double_uv_df["date"],
            y=double_uv_df["close_price"],
            mode="markers",
            name="Buy Zone Days",
            marker=dict(
                color="red",
                size=8,
                symbol="circle",
                line=dict(color="darkred", width=1)
            ),
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br>" +
                          "<b>Price:</b> $%{y:,.2f}<br>" +
                          "<b>🎯 Double Undervalued!</b><br>" +
                          "<extra></extra>"
        ))
    
    # Update layout
    fig.update_layout(
        title={
            "text": "Bitcoin Price vs Fair Value Indicators<br><sub>Red dots = Double Undervaluation Buy Zones</sub>",
            "x": 0.5,
            "xanchor": "center"
        },
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        yaxis_type="log",  # Log scale to better show the power law growth
        hovermode="x unified",
        template="plotly_white",
        height=700,
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)"
        )
    )
    
    # Add range slider and selectors
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=2, label="2Y", step="year", stepmode="backward"),
                dict(step="all", label="All")
            ])
        )
    )
    
    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    fig.write_html(str(output_path), auto_open=auto_open)
    
    print(f"✓ Saved price comparison chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")
    
    return str(output_path)


def plot_double_undervaluation_stats(
    df: pd.DataFrame,
    output_filename: str = "double_uv_stats.html",
    auto_open: bool = False
) -> str:
    """
    Create statistical charts about double undervaluation occurrences.
    
    Shows:
    - Distribution of double undervaluation by year
    - Duration of double undervaluation periods
    
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
    
    # Count double undervaluation days by year
    yearly_stats = plot_df.groupby("year").agg({
        "is_double_undervalued": ["sum", "count"]
    }).reset_index()
    yearly_stats.columns = ["year", "double_uv_days", "total_days"]
    yearly_stats["percentage"] = (yearly_stats["double_uv_days"] / yearly_stats["total_days"]) * 100
    
    # Create subplots
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("Double Undervaluation Days by Year", 
                        "Percentage of Days in Buy Zone by Year"),
        vertical_spacing=0.15
    )
    
    # Bar chart: absolute days
    fig.add_trace(go.Bar(
        x=yearly_stats["year"],
        y=yearly_stats["double_uv_days"],
        name="Buy Zone Days",
        marker_color="rgb(220, 53, 69)",
        hovertemplate="<b>Year:</b> %{x}<br>" +
                      "<b>Days:</b> %{y}<br>" +
                      "<extra></extra>"
    ), row=1, col=1)
    
    # Bar chart: percentage
    fig.add_trace(go.Bar(
        x=yearly_stats["year"],
        y=yearly_stats["percentage"],
        name="Percentage",
        marker_color="rgb(255, 127, 80)",
        hovertemplate="<b>Year:</b> %{x}<br>" +
                      "<b>Percentage:</b> %{y:.1f}%<br>" +
                      "<extra></extra>",
        showlegend=False
    ), row=2, col=1)
    
    # Update layout
    fig.update_layout(
        title_text="Double Undervaluation Statistics by Year",
        height=800,
        template="plotly_white",
        showlegend=True
    )
    
    fig.update_yaxes(title_text="Days", row=1, col=1)
    fig.update_yaxes(title_text="Percentage (%)", row=2, col=1)
    fig.update_xaxes(title_text="Year", row=2, col=1)
    
    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    fig.write_html(str(output_path), auto_open=auto_open)
    
    print(f"✓ Saved statistics chart to: {output_path}")
    if auto_open:
        print("  Opening in browser...")
    
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
    
    # Statistics chart
    print("\n3. Statistics Chart...")
    charts["statistics"] = plot_double_undervaluation_stats(df, auto_open=False)
    
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

