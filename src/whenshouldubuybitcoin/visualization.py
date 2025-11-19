"""
Visualization module for Bitcoin valuation analysis.

This module provides interactive charts using Plotly to visualize:
- DCA and Trend ratios over time
- Double undervaluation zones
- Price vs fair value comparisons
"""

from pathlib import Path
from typing import Optional, Tuple

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
                    
                    // Check what changed in this event
                    var isXAxisChange = false;
                    var isYAxisRangeChange = false;
                    
                    for (var key in eventData) {
                        // Check for x-axis range changes (user zoom/box select)
                        if (key.indexOf('xaxis.range') === 0 || key === 'xaxis.autorange') {
                            isXAxisChange = true;
                        }
                        // Check for y-axis RANGE changes (not autorange, which is our own update)
                        if (key.indexOf('yaxis.range') === 0) {
                            isYAxisRangeChange = true;
                        }
                    }
                    
                    // If both x and y ranges changed, user did a box-select, so DON'T auto-scale
                    if (isXAxisChange && isYAxisRangeChange) {
                        // Box-select: user manually set both axes, respect their selection
                        var xaxis = gd._fullLayout.xaxis;
                        var currentXRange = xaxis && xaxis.range && !xaxis.autorange ? xaxis.range : null;
                        if (currentXRange) {
                            prevXRange = [currentXRange[0], currentXRange[1]];
                        }
                        return;
                    }
                    
                    // If only x-axis changed, check if the range actually changed
                    if (isXAxisChange) {
                        var xaxis = gd._fullLayout.xaxis;
                        var currentXRange = xaxis && xaxis.range && !xaxis.autorange ? xaxis.range : null;
                        
                        // Check if range actually changed (to prevent duplicate auto-scale calls)
                        var rangeChanged = false;
                        if (currentXRange && prevXRange) {
                            if (Math.abs(currentXRange[0] - prevXRange[0]) > 1 || 
                                Math.abs(currentXRange[1] - prevXRange[1]) > 1) {
                                rangeChanged = true;
                            }
                        } else if (currentXRange !== prevXRange) {
                            rangeChanged = true;
                        }
                        
                        // Only trigger auto-scale if range actually changed
                        if (rangeChanged && currentXRange) {
                            prevXRange = [currentXRange[0], currentXRange[1]];
                            forceYAxisAutorange();
                        }
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
                    var yaxis = gd._fullLayout.yaxis;
                    
                    if (xaxis && xaxis.range && !xaxis.autorange) {
                        // If y-axis is also manually set (not autorange), this was a box-select
                        // Don't override user's manual y-axis selection
                        if (yaxis && yaxis.range && !yaxis.autorange) {
                            // Box-select: both axes manually set, just update tracking
                            var currentXRange = [xaxis.range[0], xaxis.range[1]];
                            if (!prevXRange || 
                                Math.abs(currentXRange[0] - prevXRange[0]) > 1 || 
                                Math.abs(currentXRange[1] - prevXRange[1]) > 1) {
                                prevXRange = [currentXRange[0], currentXRange[1]];
                            }
                            return;
                        }
                        
                        // Only x-axis manually set: normal zoom, apply auto-scale
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

    # Add range slider
    fig.update_xaxes(
        rangeslider_visible=True,
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
        status_color = "rgb(40, 167, 69)"
    elif current_rate < 120:
        status = "Weak USD (110-120)"
        status_color = "rgb(100, 200, 100)"
    elif current_rate < 130:
        status = "Moderate (120-130)"
        status_color = "rgb(150, 150, 150)"
    elif current_rate < 140:
        status = "Moderate-Strong (130-140)"
        status_color = "rgb(200, 150, 100)"
    elif current_rate < 150:
        status = "Strong USD (140-150)"
        status_color = "rgb(255, 149, 0)"
    elif current_rate < 160:
        status = "Very Strong USD (150-160)"
        status_color = "rgb(255, 100, 100)"
    else:
        status = "Extremely Strong USD (Above 160)"
        status_color = "rgb(220, 53, 69)"

    # Update layout
    fig.update_layout(
        title={
            "text": f"USD/JPY Exchange Rate<br><sub>Current: {current_rate:.2f} - {status}</sub>",
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis_title="Date",
        yaxis_title="USD/JPY Rate",
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
                    dict(count=5, label="5Y", step="year", stepmode="backward"),
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
        margin=dict(t=140, b=150, r=50, l=50),  # Increased top margin for legend, standard sides
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

    # Add risk rules text as annotation
    risk_rules_text = f"""
    <b>COMBINED RISK RULES:</b><br>
    • <b>Highest Risk (Systemic Crisis):</b> USD/JPY ≥ 155 AND Spread < 2.0%<br>
    • <b>Very High Risk:</b> USD/JPY ≥ 150 AND Spread < 2.0%<br>
    • <b>Elevated Risk:</b> USD/JPY ≥ 150 AND Spread 2.0-2.5%<br>
    • <b>Neutral:</b> USD/JPY 142-150 AND Spread > 2.5%<br>
    • <b>Safe:</b> USD/JPY 135-142 AND Spread > 2.5%<br>
    <br>
    <b>Current Status:</b> {risk_description}<br>
    <span style="font-size: 9px; color: gray;">Data Source: {data_source}</span>
    """

    fig.add_annotation(
        text=risk_rules_text,
        xref="paper",
        yref="paper",
        x=0.5,
        y=-0.25,  # Position below the chart/slider
        xanchor="center",
        yanchor="top",
        showarrow=False,
        align="left",
        bgcolor="rgba(255, 255, 255, 0.9)",
        bordercolor="rgba(0, 0, 0, 0.2)",
        borderwidth=1,
        font=dict(size=10),
    )

    # Save to HTML
    output_dir = get_output_dir()
    output_path = output_dir / output_filename
    fig.write_html(str(output_path), auto_open=auto_open)

    # Add JavaScript to enable y-axis auto-scaling when x-axis range changes
    add_yaxis_autoscale_script(output_path)

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
