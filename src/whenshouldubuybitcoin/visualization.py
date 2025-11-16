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


def add_yaxis_autoscale_script(html_path: Path) -> None:
    """
    Add JavaScript code to enable y-axis auto-scaling when x-axis range changes.

    This function reads the HTML file, injects JavaScript code that listens for
    x-axis range changes and automatically adjusts the y-axis to fit visible data.

    Args:
        html_path: Path to the HTML file to modify
    """
    if not html_path.exists():
        return

    # Read the HTML content
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # JavaScript code to enable y-axis auto-scaling on x-axis range changes
    # Find the plotly graph div by class and attach event listener
    autoscale_script = """
    <script>
    (function() {
        // Enable y-axis auto-scaling when x-axis range changes (including box select/zoom)
        function setupYAxisAutoScale() {
            // Find all plotly graph divs
            var plotlyDivs = document.querySelectorAll('.plotly-graph-div');
            
            plotlyDivs.forEach(function(gd) {
                if (!gd || !gd._fullLayout) {
                    // Retry if Plotly not ready
                    setTimeout(setupYAxisAutoScale, 200);
                    return;
                }
                
                // Track previous x-axis range
                var prevXRange = null;
                var updateTimeout = null;
                var isUpdatingYAxis = false;  // Flag to prevent recursive updates
                
                // Function to force y-axis autorange update
                function forceYAxisAutorange() {
                    // Prevent recursive calls
                    if (isUpdatingYAxis) {
                        return;
                    }
                    
                    if (updateTimeout) {
                        clearTimeout(updateTimeout);
                    }
                    
                    updateTimeout = setTimeout(function() {
                        try {
                            // Get current x-axis state
                            var xaxis = gd._fullLayout.xaxis;
                            var currentXRange = xaxis.range && !xaxis.autorange ? xaxis.range : null;
                            
                            // Check if x-axis range actually changed
                            var shouldUpdate = false;
                            if (currentXRange && prevXRange) {
                                // Compare ranges (allow 1ms difference for floating point)
                                if (Math.abs(currentXRange[0] - prevXRange[0]) > 1 || 
                                    Math.abs(currentXRange[1] - prevXRange[1]) > 1) {
                                    shouldUpdate = true;
                                }
                            } else if (currentXRange !== prevXRange) {
                                shouldUpdate = true;
                            }
                            
                            if (shouldUpdate || currentXRange) {
                                // Update previous range
                                prevXRange = currentXRange ? [currentXRange[0], currentXRange[1]] : null;
                                
                                // Set flag to prevent recursive updates
                                isUpdatingYAxis = true;
                                
                                // Force y-axis autorange - use a single relayout call
                                Plotly.relayout(gd, {
                                    'yaxis.autorange': true
                                }).then(function() {
                                    // Reset flag after a short delay to allow layout to settle
                                    setTimeout(function() {
                                        isUpdatingYAxis = false;
                                    }, 100);
                                }).catch(function(err) {
                                    // Reset flag on error
                                    isUpdatingYAxis = false;
                                });
                            }
                        } catch(e) {
                            console.error('Error updating y-axis autorange:', e);
                            isUpdatingYAxis = false;
                        }
                    }, 100);
                }
                
                // Listen for relayout events, but only respond to user-initiated x-axis changes
                gd.on('plotly_relayout', function(eventData) {
                    // Skip if we're currently updating y-axis (to prevent recursion)
                    if (isUpdatingYAxis) {
                        return;
                    }
                    
                    // Check if this is a user-initiated x-axis change (not y-axis change)
                    var isXAxisChange = false;
                    var isYAxisChange = false;
                    
                    for (var key in eventData) {
                        // Check for x-axis range changes (user zoom/box select)
                        if (key.indexOf('xaxis.range') === 0 || key === 'xaxis.autorange') {
                            isXAxisChange = true;
                        }
                        // Check for y-axis changes (likely from our own updates)
                        if (key.indexOf('yaxis') === 0) {
                            isYAxisChange = true;
                        }
                    }
                    
                    // Only update if it's an x-axis change and NOT a y-axis change
                    // (y-axis changes are likely from our own updates)
                    if (isXAxisChange && !isYAxisChange) {
                        forceYAxisAutorange();
                    }
                });
                
                // Use afterplot event as a backup - it fires after all rendering is complete
                // This is safer because it won't trigger during our own relayout calls
                gd.on('plotly_afterplot', function() {
                    // Skip if we're updating
                    if (isUpdatingYAxis) {
                        return;
                    }
                    
                    // Check if x-axis has a manual range (indicating zoom/box select)
                    var xaxis = gd._fullLayout.xaxis;
                    if (xaxis && xaxis.range && !xaxis.autorange) {
                        var currentXRange = [xaxis.range[0], xaxis.range[1]];
                        
                        // Check if range actually changed
                        var rangeChanged = false;
                        if (prevXRange) {
                            if (Math.abs(currentXRange[0] - prevXRange[0]) > 1 || 
                                Math.abs(currentXRange[1] - prevXRange[1]) > 1) {
                                rangeChanged = true;
                            }
                        } else {
                            rangeChanged = true;
                        }
                        
                        if (rangeChanged) {
                            prevXRange = [currentXRange[0], currentXRange[1]];
                            forceYAxisAutorange();
                        }
                    }
                });
                
                // Initialize previous range
                var xaxis = gd._fullLayout.xaxis;
                if (xaxis && xaxis.range && !xaxis.autorange) {
                    prevXRange = [xaxis.range[0], xaxis.range[1]];
                }
            });
        }
        
        // Setup when page is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function() {
                setTimeout(setupYAxisAutoScale, 500);
            });
        } else {
            // DOM already loaded, wait for Plotly to initialize
            setTimeout(setupYAxisAutoScale, 1000);
        }
    })();
    </script>
    """

    # Insert the script before the closing </body> tag
    if "</body>" in html_content:
        html_content = html_content.replace("</body>", autoscale_script + "\n</body>")
        # Write back to file
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)


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
        annotation_text="Fair Value (1.0)",
        annotation_position="right",
    )

    # Add ahr999 threshold lines
    fig.add_hline(
        y=0.45,
        line_dash="dot",
        line_color="rgb(40, 167, 69)",
        line_width=2,
        annotation_text="🔥 ahr999 Bottom Zone (0.45)",
        annotation_position="left",
        annotation_font_color="rgb(40, 167, 69)",
    )

    fig.add_hline(
        y=1.2,
        line_dash="dot",
        line_color="rgb(255, 149, 0)",
        line_width=2,
        annotation_text="⚠️ ahr999 Watch Zone (1.2)",
        annotation_position="left",
        annotation_font_color="rgb(255, 149, 0)",
    )

    # Update layout
    fig.update_layout(
        title={
            "text": "Bitcoin Valuation Ratios & ahr999 Index<br><sub>Red shaded areas = Double Undervaluation | ahr999 < 0.45 = Bottom Zone | ahr999 < 1.2 = DCA Zone</sub>",
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis_title="Date",
        yaxis_title="Ratio Value",
        yaxis=dict(
            autorange=True,  # Enable auto-scaling for y-axis
            fixedrange=False,  # Allow y-axis to be zoomed and auto-adjusted
        ),
        hovermode="x unified",
        template="plotly_white",
        height=650,
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)",
        ),
    )

    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list(
                [
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(count=2, label="2Y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ]
            )
        ),
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    fig.write_html(str(output_path), auto_open=auto_open)

    # Add JavaScript to enable y-axis auto-scaling when x-axis range changes
    add_yaxis_autoscale_script(output_path)

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

    # Add range slider and selectors
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=list(
                [
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(count=2, label="2Y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ]
            )
        ),
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    fig.write_html(str(output_path), auto_open=auto_open)

    # Add JavaScript to enable y-axis auto-scaling when x-axis range changes
    add_yaxis_autoscale_script(output_path)

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
    yearly_stats = (
        plot_df.groupby("year")
        .agg({"is_double_undervalued": ["sum", "count"]})
        .reset_index()
    )
    yearly_stats.columns = ["year", "double_uv_days", "total_days"]
    yearly_stats["percentage"] = (
        yearly_stats["double_uv_days"] / yearly_stats["total_days"]
    ) * 100

    # Create subplots
    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=(
            "Double Undervaluation Days by Year",
            "Percentage of Days in Buy Zone by Year",
        ),
        vertical_spacing=0.15,
    )

    # Bar chart: absolute days
    fig.add_trace(
        go.Bar(
            x=yearly_stats["year"],
            y=yearly_stats["double_uv_days"],
            name="Buy Zone Days",
            marker_color="rgb(220, 53, 69)",
            hovertemplate="<b>Year:</b> %{x}<br>"
            + "<b>Days:</b> %{y}<br>"
            + "<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Bar chart: percentage
    fig.add_trace(
        go.Bar(
            x=yearly_stats["year"],
            y=yearly_stats["percentage"],
            name="Percentage",
            marker_color="rgb(255, 127, 80)",
            hovertemplate="<b>Year:</b> %{x}<br>"
            + "<b>Percentage:</b> %{y:.1f}%<br>"
            + "<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Update layout
    fig.update_layout(
        title_text="Double Undervaluation Statistics by Year",
        height=800,
        template="plotly_white",
        showlegend=True,
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
