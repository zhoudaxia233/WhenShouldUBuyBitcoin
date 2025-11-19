"""
Tests for y-axis auto-scale functionality in charts.

These tests verify that the JavaScript code for y-axis auto-scaling
is correctly embedded in generated charts and contains the necessary
logic to handle box-select zoom correctly.
"""

import pytest
import pandas as pd
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from whenshouldubuybitcoin.visualization import (
    plot_valuation_ratios,
    plot_price_comparison,
)


# Constants for test data generation
TEST_DATA_DAYS = 365
TEST_START_DATE = "2020-01-01"
TEST_BASE_PRICE = 100.0
TEST_PRICE_GROWTH_RATE = 0.01
TEST_RATIO_BASE = 1.0
TEST_RATIO_DCA_GROWTH = 0.001
TEST_RATIO_TREND_GROWTH = 0.0005
TEST_AHR999_BASE = 0.5
TEST_AHR999_GROWTH = 0.001
TEST_DCA_MULTIPLIER = 0.95
TEST_TREND_MULTIPLIER = 0.98


@pytest.fixture
def sample_dataframe():
    """Create a sample DataFrame for testing with configurable parameters."""
    end_date = datetime.strptime(TEST_START_DATE, "%Y-%m-%d") + timedelta(days=TEST_DATA_DAYS - 1)
    dates = pd.date_range(start=TEST_START_DATE, end=end_date, freq="D")
    
    num_days = len(dates)
    data = {
        "date": dates,
        "close_price": [TEST_BASE_PRICE * (1 + i * TEST_PRICE_GROWTH_RATE) for i in range(num_days)],
        "ratio_dca": [TEST_RATIO_BASE + i * TEST_RATIO_DCA_GROWTH for i in range(num_days)],
        "ratio_trend": [TEST_RATIO_BASE + i * TEST_RATIO_TREND_GROWTH for i in range(num_days)],
        "ahr999": [TEST_AHR999_BASE + i * TEST_AHR999_GROWTH for i in range(num_days)],
        "is_double_undervalued": [i % 10 == 0 for i in range(num_days)],
        "dca_cost": [TEST_BASE_PRICE * TEST_DCA_MULTIPLIER * (1 + i * TEST_PRICE_GROWTH_RATE) for i in range(num_days)],
        "trend_value": [TEST_BASE_PRICE * TEST_TREND_MULTIPLIER * (1 + i * TEST_PRICE_GROWTH_RATE) for i in range(num_days)],
    }
    return pd.DataFrame(data)


def test_yaxis_autoscale_script_contains_box_select_detection(sample_dataframe):
    """Test that the auto-scale script detects box-select events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate a chart
        output_path = Path(tmpdir) / "test_chart.html"
        plot_valuation_ratios(
            sample_dataframe, 
            output_filename=str(output_path),
            auto_open=False
        )
        
        # Read the generated HTML
        html_content = output_path.read_text()
        
        # Verify the script contains logic to detect box-select
        # (when both x and y axis ranges change)
        assert "isYAxisRangeChange" in html_content, \
            "Script should detect y-axis range changes"
        assert "yaxis.range" in html_content, \
            "Script should check for y-axis range changes"
        

def test_yaxis_autoscale_script_respects_box_select(sample_dataframe):
    """Test that the auto-scale script respects box-select zoom."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_chart.html"
        plot_valuation_ratios(
            sample_dataframe,
            output_filename=str(output_path),
            auto_open=False
        )
        
        html_content = output_path.read_text()
        
        # Verify the plotly_relayout handler has logic to skip auto-scale
        # when both x and y ranges change (box-select)
        assert "if (isXAxisChange && isYAxisRangeChange)" in html_content, \
            "Should check for both x and y axis changes (box-select)"
        assert "return;" in html_content, \
            "Should return early for box-select to respect user's y-axis selection"


def test_yaxis_autoscale_script_afterplot_respects_manual_y(sample_dataframe):
    """Test that afterplot event handler respects manual y-axis setting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_chart.html"
        plot_price_comparison(
            sample_dataframe,
            output_filename=str(output_path),
            auto_open=False
        )
        
        html_content = output_path.read_text()
        
        # Verify afterplot handler checks if y-axis is manually set
        assert "plotly_afterplot" in html_content, \
            "Should have afterplot event handler"
        assert "yaxis && yaxis.range && !yaxis.autorange" in html_content, \
            "Should check if y-axis is manually set (not autorange)"


def test_yaxis_autoscale_prevents_duplicate_calls(sample_dataframe):
    """Test that the script prevents duplicate auto-scale calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_chart.html"
        plot_valuation_ratios(
            sample_dataframe,
            output_filename=str(output_path),
            auto_open=False
        )
        
        html_content = output_path.read_text()
        
        # Verify it tracks previous x-axis range to prevent duplicates
        assert "prevXRange" in html_content, \
            "Should track previous x-axis range"
        assert "rangeChanged" in html_content, \
            "Should check if range actually changed"
        # Check that it compares ranges (implementation detail may vary)
        assert ("currentXRange[0]" in html_content and "prevXRange[0]" in html_content), \
            "Should compare current and previous ranges"


def test_yaxis_autoscale_has_recursion_guard(sample_dataframe):
    """Test that the script has a recursion guard."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_chart.html"
        plot_valuation_ratios(
            sample_dataframe,
            output_filename=str(output_path),
            auto_open=False
        )
        
        html_content = output_path.read_text()
        
        # Verify there's a flag to prevent recursive updates
        assert "isUpdatingYAxis" in html_content, \
            "Should have flag to prevent recursion"
        assert "if (isUpdatingYAxis)" in html_content, \
            "Should check flag and return early if updating"


def test_yaxis_autoscale_updates_on_x_only_change(sample_dataframe):
    """Test that auto-scale triggers when only x-axis changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_chart.html"
        plot_valuation_ratios(
            sample_dataframe,
            output_filename=str(output_path),
            auto_open=False
        )
        
        html_content = output_path.read_text()
        
        # Verify it calls forceYAxisAutorange when only x-axis changes
        assert "forceYAxisAutorange()" in html_content, \
            "Should have function to force y-axis autorange"
        assert "'yaxis.autorange': true" in html_content, \
            "Should set yaxis.autorange to true"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
