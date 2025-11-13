#!/usr/bin/env python3
"""
Main CLI entry point for When Should U Buy Bitcoin.

Step 5 MVP: Full analysis with data persistence (CSV storage).
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from whenshouldubuybitcoin.data_fetcher import fetch_btc_history, get_latest_btc_price
from whenshouldubuybitcoin.metrics import (
    compute_valuation_metrics,
    get_dca_summary,
    get_trend_summary,
    get_double_undervaluation_summary,
)
from whenshouldubuybitcoin.persistence import (
    load_existing_metrics,
    save_metrics,
    merge_with_existing,
    get_days_to_fetch,
)
from whenshouldubuybitcoin.visualization import generate_all_charts


def main():
    """Main entry point for Step 5 MVP."""
    print("=" * 80)
    print("When Should U Buy Bitcoin - Step 5 MVP")
    print("=" * 80)
    print()

    try:
        # Step 1: Try to load existing data
        print("=" * 80)
        print("STEP 1: Load Existing Data")
        print("=" * 80)
        existing_df = load_existing_metrics()

        # Step 2: Determine how much new data to fetch
        print("\n" + "=" * 80)
        print("STEP 2: Fetch New/Updated Price Data")
        print("=" * 80)
        days_to_fetch = get_days_to_fetch(existing_df, buffer_days=30)

        # Fetch price data
        new_price_df = fetch_btc_history(days=days_to_fetch)

        # Step 3: Merge with existing data (if any)
        if existing_df is not None:
            print("\n" + "=" * 80)
            print("STEP 3: Merge with Existing Data")
            print("=" * 80)
            # Keep only the price data from new fetch, merge will combine
            price_df = merge_with_existing(
                new_price_df, existing_df[["date", "close_price"]]
            )
        else:
            price_df = new_price_df

        # Step 4: Calculate all valuation metrics on merged data
        print("\n" + "=" * 80)
        print("STEP 4: Calculate Valuation Metrics")
        print("=" * 80)
        print("  - 200-day DCA cost")
        print("  - Exponential trend model")
        print("  - Double undervaluation detection")
        df = compute_valuation_metrics(price_df, dca_window=200)

        # Step 5: Save updated metrics to CSV
        print("\n" + "=" * 80)
        print("STEP 5: Save to CSV")
        print("=" * 80)
        save_success = save_metrics(df)
        if save_success:
            print("✓ Data persistence complete!")
        else:
            print("⚠ Warning: Failed to save data")

        print("\n" + "=" * 80)
        print("PRICE STATISTICS")
        print("=" * 80)
        print(f"\nTotal days: {len(df)}")
        print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        print(f"\nPrice statistics:")
        print(f"  Current: ${df['close_price'].iloc[-1]:,.2f}")
        print(f"  Min:     ${df['close_price'].min():,.2f}")
        print(f"  Max:     ${df['close_price'].max():,.2f}")
        print(f"  Mean:    ${df['close_price'].mean():,.2f}")

        # DCA Summary
        dca_summary = get_dca_summary(df)

        print("\n" + "=" * 80)
        print("200-DAY DCA COST ANALYSIS")
        print("=" * 80)
        print(
            f"\nDays analyzed (with 200+ days history): {dca_summary['total_days_analyzed']}"
        )
        print(f"\nCurrent Status:")
        print(f"  Price:           ${dca_summary['latest_price']:,.2f}")
        print(f"  200-day DCA:     ${dca_summary['latest_dca_cost']:,.2f}")
        print(f"  Price/DCA Ratio:  {dca_summary['latest_ratio']:.3f}")
        print(f"  Status:          {dca_summary['latest_status']}")

        print(f"\nHistorical DCA Metrics:")
        print(
            f"  Days below DCA:      {dca_summary['days_below_dca']} ({dca_summary['pct_days_below_dca']:.1f}%)"
        )
        print(f"  Min Price/DCA ratio: {dca_summary['min_ratio']:.3f}")
        print(f"  Max Price/DCA ratio: {dca_summary['max_ratio']:.3f}")
        print(f"  Avg Price/DCA ratio: {dca_summary['mean_ratio']:.3f}")

        # Trend Summary
        trend_summary = get_trend_summary(df)

        print("\n" + "=" * 80)
        print("EXPONENTIAL TREND ANALYSIS")
        print("=" * 80)
        print(f"\nModel: price(t) = a × exp(b × t)")
        print(f"  where t = days since {df['date'].iloc[0].date()}")
        print(f"\nFitted Parameters:")
        print(f"  a (coefficient):      {trend_summary['trend_coefficient_a']:,.2f}")
        print(
            f"  b (growth rate):      {trend_summary['trend_growth_rate_b']:.6f} per day"
        )
        print(f"  Daily growth:         {trend_summary['daily_growth_rate_pct']:.4f}%")
        print(f"  Annual growth:        {trend_summary['annual_growth_rate_pct']:.2f}%")

        print(f"\nCurrent Status:")
        print(f"  Price:             ${trend_summary['latest_price']:,.2f}")
        print(f"  Trend (Fair Value): ${trend_summary['latest_trend']:,.2f}")
        print(f"  Price/Trend Ratio:  {trend_summary['latest_ratio']:.3f}")
        print(f"  Status:            {trend_summary['latest_status']}")

        print(f"\nHistorical Trend Metrics:")
        print(
            f"  Days below trend:       {trend_summary['days_below_trend']} ({trend_summary['pct_days_below_trend']:.1f}%)"
        )
        print(f"  Min Price/Trend ratio:  {trend_summary['min_ratio']:.3f}")
        print(f"  Max Price/Trend ratio:  {trend_summary['max_ratio']:.3f}")
        print(f"  Avg Price/Trend ratio:  {trend_summary['mean_ratio']:.3f}")

        # Double Undervaluation Summary
        double_uv_summary = get_double_undervaluation_summary(df)

        print("\n" + "=" * 80)
        print("🎯 DOUBLE UNDERVALUATION ANALYSIS")
        print("=" * 80)
        print("\nBuy Zone = Price < DCA Cost AND Price < Trend (BOTH conditions)")

        print(f"\n📊 Current Status:")
        print(f"  Price:              ${double_uv_summary['current_price']:,.2f}")
        print(
            f"  200-day DCA:        ${double_uv_summary['current_dca']:,.2f} (ratio: {double_uv_summary['current_ratio_dca']:.3f})"
        )
        print(
            f"  Exponential Trend:  ${double_uv_summary['current_trend']:,.2f} (ratio: {double_uv_summary['current_ratio_trend']:.3f})"
        )

        if double_uv_summary["is_currently_double_undervalued"]:
            print("\n  🟢 STATUS: DOUBLE UNDERVALUED - BUY ZONE ACTIVE! 🟢")
            print("  Both conditions are met:")
            print("    ✓ Price is below 200-day DCA cost")
            print("    ✓ Price is below long-term exponential trend")
        else:
            print("\n  🔴 STATUS: NOT in double undervaluation zone")
            if double_uv_summary["current_ratio_dca"] >= 1.0:
                print(
                    f"    ✗ Price is ABOVE 200-day DCA cost (by {(double_uv_summary['current_ratio_dca']-1)*100:.1f}%)"
                )
            else:
                print(
                    f"    ✓ Price is below 200-day DCA cost (by {(1-double_uv_summary['current_ratio_dca'])*100:.1f}%)"
                )

            if double_uv_summary["current_ratio_trend"] >= 1.0:
                print(
                    f"    ✗ Price is ABOVE exponential trend (by {(double_uv_summary['current_ratio_trend']-1)*100:.1f}%)"
                )
            else:
                print(
                    f"    ✓ Price is below exponential trend (by {(1-double_uv_summary['current_ratio_trend'])*100:.1f}%)"
                )

        print(
            f"\n📈 Historical Statistics (last {double_uv_summary['total_days_analyzed']} days):"
        )
        print(
            f"  Days below DCA:              {double_uv_summary['days_below_dca']:>5} ({double_uv_summary['pct_below_dca']:>5.1f}%)"
        )
        print(
            f"  Days below Trend:            {double_uv_summary['days_below_trend']:>5} ({double_uv_summary['pct_below_trend']:>5.1f}%)"
        )
        print(
            f"  Days DOUBLE undervalued:     {double_uv_summary['days_double_undervalued']:>5} ({double_uv_summary['pct_double_undervalued']:>5.1f}%) ⭐"
        )

        print(f"\n🔍 Double Undervaluation Periods:")
        print(
            f"  Total number of periods:     {double_uv_summary['num_double_uv_periods']}"
        )

        if double_uv_summary["num_double_uv_periods"] > 0:
            print(f"\n  Recent periods (last 5):")
            for i, period in enumerate(double_uv_summary["double_uv_periods"][-5:], 1):
                print(
                    f"    {i}. {period['start'].strftime('%Y-%m-%d')} to {period['end'].strftime('%Y-%m-%d')} ({period['days']} days)"
                )
                print(
                    f"       Avg price: ${period['avg_price']:,.2f}, Min price: ${period['min_price']:,.2f}"
                )

            if double_uv_summary["last_double_uv_date"]:
                print(
                    f"\n  Last occurrence: {double_uv_summary['last_double_uv_date'].strftime('%Y-%m-%d')}"
                )
                print(
                    f"  Days since:      {double_uv_summary['days_since_last_double_uv']} days ago"
                )
        else:
            print("  No double undervaluation periods found in the dataset.")

        print("\n" + "=" * 80)
        print("INTERPRETATION")
        print("=" * 80)
        print("\n1. DCA Cost (200-day):")
        print("   • Short-term valuation metric")
        print("   • Ratio < 1.0 = Price below recent average cost basis")

        print("\n2. Exponential Trend:")
        print("   • Long-term valuation metric (fitted to all historical data)")
        print("   • Ratio < 1.0 = Price below long-term growth trend")
        print(
            f"   • BTC has grown at ~{trend_summary['annual_growth_rate_pct']:.0f}% annually (historically)"
        )

        print("\n3. Double Undervaluation (Buy Zone):")
        print("   • RARE opportunity when BOTH conditions are met")
        print(
            f"   • Historically occurs only ~{double_uv_summary['pct_double_undervalued']:.1f}% of the time"
        )
        print("   • These periods often preceded strong recoveries")

        # Show sample data with all metrics
        print("\n" + "=" * 80)
        print("SAMPLE DATA (Last 10 days)")
        print("=" * 80)
        display_cols = [
            "date",
            "close_price",
            "dca_cost",
            "ratio_dca",
            "trend_value",
            "ratio_trend",
            "is_double_undervalued",
        ]
        sample_df = df[display_cols].tail(10).copy()
        # Format for better display
        sample_df["date"] = sample_df["date"].dt.strftime("%Y-%m-%d")
        # Replace True/False with symbols for readability
        sample_df["is_double_undervalued"] = sample_df["is_double_undervalued"].map(
            {True: "🟢 YES", False: "❌ No"}
        )
        print(sample_df.to_string(index=False))

        # Generate interactive charts
        generate_all_charts(df, auto_open=True)

        print("\n" + "=" * 80)
        print("✓ Step 5+ MVP Complete!")
        print("=" * 80)
        print("\n🎉 Data is now persisted to CSV for efficient daily updates!")
        print(f"   Data: data/btc_metrics.csv")
        print(f"   Charts: charts/ (3 interactive HTML files)")
        print("\nNext run will:")
        print("  - Load existing data from CSV")
        print("  - Only fetch recent days (not full 2000 days)")
        print("  - Update metrics efficiently")
        print("  - Regenerate charts with latest data")
        print("\nNext: Step 6 will add daily update logic & scheduling")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
