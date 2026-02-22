#!/usr/bin/env python3
"""
Main CLI entry point for When Should U Buy Bitcoin.

Step 5+ MVP: Full analysis with data persistence, visualization, and real-time checks.

Usage:
    python main.py                  # Full analysis and update
    python main.py --check-now      # Quick real-time buy zone check
    python main.py --realtime       # Same as --check-now
"""

import sys
from pathlib import Path
import pandas as pd
import json
from datetime import datetime
import tempfile

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))
# Add dca_service/src to path for shared logic
sys.path.insert(0, str(Path(__file__).parent / "dca_service/src"))

from whenshouldubuybitcoin.data_fetcher import (
    fetch_btc_history,
    fetch_usdjpy_history,
    fetch_yield_data,
    fetch_macro_liquidity_indicators,
    get_latest_btc_price,
)
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
from whenshouldubuybitcoin.providers.binance_api import fetch_btc_funding_rate, fetch_open_interest_history
from whenshouldubuybitcoin.providers.alternative_me import fetch_fear_and_greed_index
from whenshouldubuybitcoin.providers.blockchain_data import fetch_hashrate_trend
from whenshouldubuybitcoin.visualization import (
    generate_all_charts,
    plot_usdjpy_risk_map,
    create_futures_oi_timeseries_chart,
    plot_net_liquidity_dashboard,
    plot_funding_credit_stress,
    plot_macro_risk_score,
)
from whenshouldubuybitcoin.realtime_check import check_realtime_status
from whenshouldubuybitcoin.daily_report import generate_daily_report


def _fmt_num(value, fmt: str, fallback: str = "N/A") -> str:
    """Format numeric CLI output safely when upstream summaries contain None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    try:
        return format(value, fmt)
    except Exception:
        return fallback


def save_oi_cache(oi_data: list, cache_path: Path) -> None:
    """Save OI data to cache file with timestamp."""
    try:
        cache_obj = {
            "timestamp": datetime.now().isoformat(),
            "data": oi_data
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(cache_obj, tmp, indent=2)
            tmp_path = Path(tmp.name)
        tmp_path.replace(cache_path)
        print(f"✓ Saved OI data to cache: {cache_path}")
    except Exception as e:
        print(f"⚠ Warning: Failed to save OI cache: {e}")


def load_oi_cache(cache_path: Path) -> tuple[list | None, str | None]:
    """Load OI data from cache file.
    
    Returns:
        Tuple of (data, timestamp_str) or (None, None) if cache doesn't exist or is invalid
    """
    try:
        if not cache_path.exists():
            return None, None
        
        with open(cache_path, 'r') as f:
            cache_obj = json.load(f)
        
        data = cache_obj.get('data')
        timestamp = cache_obj.get('timestamp')
        
        if data and timestamp:
            # Parse timestamp to check age
            cache_time = datetime.fromisoformat(timestamp)
            age_hours = (datetime.now() - cache_time).total_seconds() / 3600
            print(f"✓ Loaded OI data from cache (age: {age_hours:.1f} hours)")
            return data, timestamp
        
        return None, None
    
    except Exception as e:
        print(f"⚠ Warning: Failed to load OI cache: {e}")
        return None, None


def main(strict_update: bool = False):
    """Main entry point for Step 5 MVP."""
    print("=" * 80)
    print("When Should U Buy Bitcoin - Step 5 MVP")
    print("=" * 80)
    print()

    try:
        # Step 1: Try to load existing data
        usdjpy_df = None
        yield_df = None
        macro_df = None
        oi_df = None
        report_status = "pending"
        component_status = {
            "valuation_charts": False,
            "usdjpy_risk_map": False,
            "macro_charts": False,
            "futures_oi_charts": False,
            "daily_report": False,
        }
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
        print("  - Power law trend model")
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
        print("POWER LAW TREND ANALYSIS")
        print("=" * 80)
        print(f"\nModel: price(t) = a × t^n")
        print(f"  where t = Bitcoin age (days since genesis: 2009-01-03)")
        print(f"  Data available from: {df['date'].iloc[0].date()}")
        print(f"\nFitted Parameters:")
        print(
            f"  a (coefficient):      {_fmt_num(trend_summary.get('trend_coefficient_a'), ',.2f')}"
        )
        print(
            f"  n (power exponent):   {_fmt_num(trend_summary.get('power_law_exponent'), '.6f')}"
        )
        growth_rate = _fmt_num(trend_summary.get("daily_growth_rate_pct"), ".4f")
        growth_rate_suffix = "% per day" if growth_rate != "N/A" else ""
        print(f"  Current growth rate:  {growth_rate}{growth_rate_suffix}")
        print(f"  Note: Growth rate decreases over time in power law model")

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
            f"  Power Law Trend:    ${double_uv_summary['current_trend']:,.2f} (ratio: {double_uv_summary['current_ratio_trend']:.3f})"
        )

        if double_uv_summary["is_currently_double_undervalued"]:
            print("\n  🟢 STATUS: DOUBLE UNDERVALUED - BUY ZONE ACTIVE! 🟢")
            print("  Both conditions are met:")
            print("    ✓ Price is below 200-day DCA cost")
            print("    ✓ Price is below long-term power law trend")
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
                    f"    ✗ Price is ABOVE power law trend (by {(double_uv_summary['current_ratio_trend']-1)*100:.1f}%)"
                )
            else:
                print(
                    f"    ✓ Price is below power law trend (by {(1-double_uv_summary['current_ratio_trend'])*100:.1f}%)"
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

        print("\n2. Power Law Trend:")
        print("   • Long-term valuation metric (fitted to all historical data)")
        print("   • Ratio < 1.0 = Price below long-term growth trend")
        print(
            f"   • Power law exponent: {_fmt_num(trend_summary.get('power_law_exponent'), '.2f')} (models network effects)"
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

        # Generate interactive charts (don't auto-open when triggered via API)
        generate_all_charts(df, auto_open=False)
        component_status["valuation_charts"] = True

        # Generate USD/JPY charts
        print("\n" + "=" * 80)
        print("GENERATING USD/JPY RISK MAP")
        print("=" * 80)
        usdjpy_df = fetch_usdjpy_history(days=None)  # Fetch all available data

        # Generate USD/JPY Risk Map
        print("\nGenerating USD/JPY Systemic Risk Map...")
        try:
            yield_df, data_source = fetch_yield_data(days=None)  # Fetch all available data
            plot_usdjpy_risk_map(usdjpy_df, yield_df, data_source=data_source, auto_open=False)
            print("✓ USD/JPY Risk Map generated successfully")
            component_status["usdjpy_risk_map"] = True
        except Exception as e:
            print(f"⚠ Warning: Failed to generate USD/JPY Risk Map: {e}")
            print("  This may be due to Yahoo Finance data limitations.")
            if strict_update:
                raise

        # Generate macro liquidity and stress charts
        print("\n" + "=" * 80)
        print("GENERATING MACRO LIQUIDITY & STRESS CHARTS")
        print("=" * 80)
        try:
            macro_df = fetch_macro_liquidity_indicators(days=None)
            plot_net_liquidity_dashboard(df, macro_df, auto_open=False)
            plot_funding_credit_stress(df, macro_df, auto_open=False)
            plot_macro_risk_score(df, macro_df, auto_open=False)
            print("✓ Macro liquidity and stress charts generated successfully")
            component_status["macro_charts"] = True
        except Exception as e:
            print(f"⚠ Warning: Failed to generate macro charts: {e}")
            print("  Continuing without macro charts.")
            if strict_update:
                raise
            
        # --- Step 6: Futures Data Analysis ---
        print("\n" + "=" * 80)
        print("STEP 6: Futures Data Analysis")
        print("=" * 80)
        
        oi_cache_path = Path("docs/data/oi_cache.json")
        oi_cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            print("Fetching Binance Open Interest History...")
            oi_data = fetch_open_interest_history(limit=500)
            
            output_dir = Path("docs/charts")
            data_source = "fresh"
            
            # If fetch failed, try to load from cache
            if not oi_data:
                print("⚠ Failed to fetch fresh OI data. Attempting to load from cache...")
                oi_data, cache_timestamp = load_oi_cache(oi_cache_path)
                if oi_data:
                    data_source = "cached"
                    print(f"✓ Using cached OI data from {cache_timestamp}")
                else:
                    print("✗ No cached OI data available. Skipping Futures OI charts.")
            else:
                # Save successful fetch to cache
                save_oi_cache(oi_data, oi_cache_path)
            
            if oi_data:
                print(f"✓ Using {data_source} OI data ({len(oi_data)} data points)")
                
                # Convert to DataFrame
                oi_df = pd.DataFrame(oi_data)
                if not oi_df.empty and 'timestamp' in oi_df.columns:
                    oi_df['timestamp'] = pd.to_datetime(oi_df['timestamp'], unit='ms')
                    oi_df['sumOpenInterestValue'] = pd.to_numeric(oi_df['sumOpenInterestValue'])
                    oi_df.rename(columns={'sumOpenInterestValue': 'oi_usd'}, inplace=True)
                    oi_df.set_index('timestamp', inplace=True)
                    
                    # Prepare BTC data for the chart
                    btc_df = df.copy()
                    if 'date' in btc_df.columns:
                        btc_df['date'] = pd.to_datetime(btc_df['date'])
                        btc_df.set_index('date', inplace=True)
                    
                    # 1. Generate Main Timeseries Chart
                    create_futures_oi_timeseries_chart(
                        btc_df=btc_df,
                        oi_df=oi_df,
                        output_path=str(output_dir / "futures_oi.html")
                    )
                    
                    # 2. Generate Quadrant Chart
                    from whenshouldubuybitcoin.visualization import create_oi_quadrant_chart
                    create_oi_quadrant_chart(
                        btc_df=btc_df,
                        oi_df=oi_df,
                        output_path=str(output_dir / "oi_quadrant.html"),
                        lookback_days=5
                    )
                    
                    print(f"✓ Generated Futures OI charts using {data_source} data")
                    component_status["futures_oi_charts"] = True
                else:
                    print("⚠ OI Data is empty or missing columns.")
                    if strict_update:
                        raise ValueError("OI data missing required columns")
            
            print("\n" + "=" * 80)
            print("STEP 7: Update Wealth Distribution Data")
            print("=" * 80)
            
            try:
                # Import here to avoid issues if dca_service dependencies aren't fully met in all envs
                from dca_service.services.distribution_scraper import fetch_distribution
                
                print("Fetching latest wealth distribution data...")
                # Force fetch (use_cache=False) to get fresh data
                distribution_data = fetch_distribution(use_cache=False)
                
                if distribution_data:
                    # Define path to save
                    json_path = Path("dca_service/src/dca_service/data/wealth_distribution.json")
                    json_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(json_path, 'w') as f:
                        json.dump(distribution_data, f, indent=2)
                    
                    print(f"✓ Updated wealth distribution data: {json_path}")
                    
                    # Verify one data point
                    if len(distribution_data) > 6:
                        # [0.1 - 1) tier is usually around index 6
                        tier_data = distribution_data[6]
                        print(f"  Sample check: {tier_data.get('tier')} -> {tier_data.get('percentile')}")
                else:
                    print("⚠ Warning: No distribution data returned")
                    
            except Exception as e:
                print(f"⚠ Warning: Failed to update wealth distribution: {e}")
                print("  Skipping this step (non-critical).")

            print("\n" + "=" * 80)
            print("✓ All steps complete!")
            print("=" * 80)
            
        except Exception as e:
            print(f"⚠ Warning: Failed to generate futures analysis: {e}")
            import traceback
            traceback.print_exc()
            if strict_update:
                raise

        print("\n" + "=" * 80)
        print("STEP 8: Generate Daily Report Summary")
        print("=" * 80)
        try:
            free_signal_snapshot = {}
            try:
                fng = fetch_fear_and_greed_index()
                if fng:
                    fng_value = fng.get("value")
                    if isinstance(fng_value, int):
                        free_signal_snapshot.update(
                            {
                                "fear_greed_value": fng_value,
                                "fear_greed_classification": fng.get("value_classification"),
                                "fear_panic_score": max(0, min(100, 100 - fng_value)),
                                "is_extreme_fear_proxy": fng_value <= 25,
                            }
                        )
            except Exception as e:
                print(f"⚠ Warning: Failed to fetch Fear & Greed snapshot: {e}")

            try:
                hashrate_change = fetch_hashrate_trend()
                if hashrate_change is not None:
                    miner_stress_proxy = (
                        "elevated"
                        if hashrate_change <= -8.0
                        else "mild"
                        if hashrate_change < 0.0
                        else "low"
                    )
                    free_signal_snapshot.update(
                        {
                            "hashrate_30d_change_pct": float(hashrate_change),
                            "miner_stress_proxy": miner_stress_proxy,
                        }
                    )
            except Exception as e:
                print(f"⚠ Warning: Failed to fetch hashrate trend snapshot: {e}")

            daily_report = generate_daily_report(
                df,
                macro_df=macro_df,
                usdjpy_df=usdjpy_df,
                yield_df=yield_df,
                oi_df=oi_df,
                free_signal_snapshot=free_signal_snapshot or None,
            )
            report_status = daily_report.get("human_summary", {}).get("generated_by", "ok")
            component_status["daily_report"] = True
            print(
                f"✓ Daily report generated ({report_status}) with {len(daily_report.get('sections', []))} sections"
            )
        except Exception as e:
            print(f"⚠ Warning: Failed to generate daily report: {e}")
            if strict_update:
                raise

        print("\n" + "=" * 80)
        print("UPDATE COMPONENT STATUS")
        print("=" * 80)
        for name, ok in component_status.items():
            mark = "✓" if ok else "✗"
            print(f"  {mark} {name}")

        if strict_update and not all(component_status.values()):
            missing = [name for name, ok in component_status.items() if not ok]
            raise RuntimeError(
                "Strict update failed. Missing components: " + ", ".join(missing)
            )



    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    args = {arg.lower() for arg in sys.argv[1:]}

    if "--check-now" in args or "--realtime" in args or "-r" in args:
        check_realtime_status(verbose=True)
        sys.exit(0)

    if "--help" in args or "-h" in args:
        print("=" * 80)
        print("When Should U Buy Bitcoin - Usage")
        print("=" * 80)
        print("\nCommands:")
        print("  python main.py                    Run full analysis and update")
        print("  python main.py --strict-update    Fail if any chart/report update step fails")
        print("  python main.py --check-now        Quick real-time buy zone check")
        print("  python main.py --realtime         Same as --check-now")
        print("  python main.py --market-health    Run full analysis and show market health")
        print("  python main.py --help             Show this help message")
        print("\nDescription:")
        print("  Full analysis: Fetches historical data, calculates metrics,")
        print("                 saves to CSV, generates interactive charts, and writes daily report")
        print("\n  Real-time check: Quickly checks current buy zone status")
        print("                   using real-time price without full update")
        print("=" * 80)
        sys.exit(0)

    known_flags = {"--strict-update"}
    unknown_flags = [arg for arg in args if arg.startswith("-") and arg not in known_flags]
    if unknown_flags:
        print(f"Unknown argument(s): {', '.join(sorted(unknown_flags))}")
        print("Use --help to see available commands")
        sys.exit(1)

    main(strict_update="--strict-update" in args)
