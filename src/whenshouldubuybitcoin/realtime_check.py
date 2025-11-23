"""
Real-time buy zone check module.

This module provides functions to check the current buy zone status
using real-time BTC prices, without waiting for daily close.
"""

import numpy as np
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict

from .data_fetcher import get_realtime_btc_price
from .persistence import load_existing_metrics
from .metrics import get_ahr999_zone, calculate_ahr999_percentile, calculate_ahr999_percentile_below_one


def calculate_distance_to_buy_zone(ratio: float) -> Dict[str, float]:
    """
    Calculate how far the price is from entering the buy zone.
    
    For a ratio to be in buy zone, it must be < 1.0.
    
    Algorithm:
    - If ratio >= 1.0: Calculate percentage drop needed to reach 1.0
      Formula: distance = (ratio - 1.0) / ratio * 100
      Example: ratio=1.05 → need to drop 4.76%
      
    - If ratio < 1.0: Already in buy zone
      Formula: below_by = (1.0 - ratio) / 1.0 * 100
      Example: ratio=0.95 → already 5% below threshold
    
    Args:
        ratio: Current price/threshold ratio
        
    Returns:
        Dictionary with:
            - in_zone: bool, whether already in buy zone (ratio < 1.0)
            - percentage: float, percentage away from zone (positive if need to drop, negative if already below)
            - direction: str, "needs_drop" or "already_below"
    """
    if ratio >= 1.0:
        # Need to drop to reach buy zone
        # If ratio = price / threshold = 1.05, need to drop:
        # (current_price - threshold) / current_price = (1.05 - 1.0) / 1.05 = 4.76%
        distance_pct = (ratio - 1.0) / ratio * 100
        return {
            "in_zone": False,
            "percentage": distance_pct,
            "direction": "needs_drop"
        }
    else:
        # Already in buy zone
        # If ratio = 0.95, already below by:
        # (threshold - current_price) / threshold = (1.0 - 0.95) / 1.0 = 5%
        below_by_pct = (1.0 - ratio) / 1.0 * 100
        return {
            "in_zone": True,
            "percentage": below_by_pct,
            "direction": "already_below"
        }


def check_realtime_status(verbose: bool = True) -> Optional[Dict]:
    """
    Check the current real-time buy zone status.
    
    This function:
    1. Loads historical metrics from CSV
    2. Fetches current real-time BTC price
    3. Calculates real-time DCA and Trend ratios
    4. Determines if in buy zone
    5. Calculates distance to buy zone for each metric
    
    Args:
        verbose: If True, prints detailed output. If False, returns data only.
        
    Returns:
        Dictionary with real-time status data, or None if error
    """
    if verbose:
        print("\n" + "=" * 80)
        print("🔴 REAL-TIME BUY ZONE CHECK")
        print("=" * 80)
    
    # Load historical data
    df = load_existing_metrics()
    if df is None or df.empty:
        if verbose:
            print("\n❌ Error: No historical data found.")
            print("   Please run 'python main.py' first to build historical dataset.")
        return None
    
    # Check data freshness
    last_data_date = df['date'].max()
    days_old = (pd.Timestamp.now() - last_data_date).days
    if days_old > 7 and verbose:
        print(f"\n⚠️  Warning: Historical data is {days_old} days old.")
        print("   Consider running 'python main.py' to update.")
    
    # Get real-time price
    if verbose:
        print("\n📡 Fetching real-time BTC price...")
    
    try:
        price_time, realtime_price = get_realtime_btc_price()
        
        if verbose:
            # Convert UTC time to Berlin time for display
            utc_time = price_time.replace(tzinfo=ZoneInfo("UTC"))
            berlin_time = utc_time.astimezone(ZoneInfo("Europe/Berlin"))
            
            print(f"   ✓ Success")
            print(f"      UTC:    {utc_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"      Berlin: {berlin_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    except Exception as e:
        if verbose:
            print(f"\n❌ Error: Failed to fetch real-time price: {e}")
        return None
    
    # Calculate real-time DCA cost
    # Use last 199 days from historical data + today's real-time price
    last_199_days = df.tail(199)
    if len(last_199_days) < 199:
        if verbose:
            print(f"\n❌ Error: Need at least 199 days of historical data.")
            print(f"   Currently have {len(last_199_days)} days.")
        return None
    
    prices_200 = list(last_199_days['close_price']) + [realtime_price]
    realtime_dca = 200.0 / sum(1.0 / p for p in prices_200)
    ratio_dca = realtime_price / realtime_dca
    
    # Calculate 180-day peak (for dynamic strategy drawdown boost)
    # Use last 179 days + today
    last_179_days = df.tail(179)
    prices_180 = list(last_179_days['close_price']) + [realtime_price]
    peak180 = max(prices_180) if prices_180 else realtime_price
    
    # Calculate real-time Trend
    # Get power law trend parameters from historical fit
    trend_a = df.attrs.get('trend_a')
    trend_b = df.attrs.get('trend_b')  # This is now the power law exponent 'n'
    
    if trend_a is None or trend_b is None:
        if verbose:
            print(f"\n❌ Error: Trend parameters not found in historical data.")
            print("   Please run 'python main.py' to calculate trend.")
        return None
    
    # Calculate Bitcoin age (days since genesis block: 2009-01-03)
    # This must match the fitting implementation!
    genesis_date = pd.Timestamp('2009-01-03')
    bitcoin_age_days = (pd.Timestamp.now() - genesis_date).days
    
    # Calculate power law trend: price = a * t^n
    # where t = Bitcoin age in days (not data age!)
    realtime_trend = trend_a * np.power(bitcoin_age_days, trend_b)
    ratio_trend = realtime_price / realtime_trend
    
    # Calculate distances to buy zone
    dca_distance = calculate_distance_to_buy_zone(ratio_dca)
    trend_distance = calculate_distance_to_buy_zone(ratio_trend)
    
    # Determine overall buy zone status
    is_double_undervalued = ratio_dca < 1.0 and ratio_trend < 1.0
    
    # Calculate ahr999 index
    realtime_ahr999 = ratio_dca * ratio_trend
    ahr999_zone = get_ahr999_zone(realtime_ahr999)
    
    # Calculate historical percentile for ahr999 (overall)
    ahr999_percentile = calculate_ahr999_percentile(df, realtime_ahr999)
    
    # Calculate percentile among days with ahr999 < 1.0 (buy zone days only)
    ahr999_percentile_below_one = calculate_ahr999_percentile_below_one(df, realtime_ahr999)
    
    # Build result
    result = {
        "timestamp": price_time,
        "realtime_price": realtime_price,
        "dca_cost": realtime_dca,
        "ratio_dca": ratio_dca,
        "dca_distance": dca_distance,
        "trend_value": realtime_trend,
        "ratio_trend": ratio_trend,
        "trend_distance": trend_distance,
        "is_double_undervalued": is_double_undervalued,
        "ahr999": realtime_ahr999,
        "ahr999_zone": ahr999_zone,
        "ahr999_percentile": ahr999_percentile,
        "ahr999_percentile_below_one": ahr999_percentile_below_one,
        "last_data_date": last_data_date,
        "days_old": days_old,
        "peak180": peak180
    }
    
    # Print detailed output
    if verbose:
        # Convert times for display
        utc_time = price_time.replace(tzinfo=ZoneInfo("UTC"))
        berlin_time = utc_time.astimezone(ZoneInfo("Europe/Berlin"))
        
        print("\n" + "=" * 80)
        print("💰 CURRENT STATUS")
        print("=" * 80)
        print(f"\n  Real-time BTC Price:  ${realtime_price:,.2f}")
        print(f"  Time (UTC):           {utc_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Time (Berlin):        {berlin_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        print("\n" + "=" * 80)
        print("📊 VALUATION METRICS")
        print("=" * 80)
        
        # DCA Analysis
        print(f"\n  🔵 200-Day DCA Cost:   ${realtime_dca:,.2f}")
        print(f"     Price/DCA Ratio:    {ratio_dca:.3f}")
        
        if dca_distance["in_zone"]:
            print(f"     Status:             ✅ IN BUY ZONE (below by {dca_distance['percentage']:.2f}%)")
        else:
            print(f"     Status:             ❌ Above threshold")
            print(f"     Distance:           Need {dca_distance['percentage']:.2f}% drop to enter zone")
        
        # Trend Analysis
        print(f"\n  🟢 Power Law Trend:    ${realtime_trend:,.2f}")
        print(f"     Price/Trend Ratio:  {ratio_trend:.3f}")
        
        if trend_distance["in_zone"]:
            print(f"     Status:             ✅ IN BUY ZONE (below by {trend_distance['percentage']:.2f}%)")
        else:
            print(f"     Status:             ❌ Above threshold")
            print(f"     Distance:           Need {trend_distance['percentage']:.2f}% drop to enter zone")
        
        # Overall Status
        print("\n" + "=" * 80)
        print("🎯 DOUBLE UNDERVALUATION STATUS")
        print("=" * 80)
        
        if is_double_undervalued:
            print("\n  🟢🟢 DOUBLE UNDERVALUATION - BUY ZONE ACTIVE! 🟢🟢")
            print("\n  Both conditions are met:")
            print("    ✓ Price is below 200-day DCA cost")
            print("    ✓ Price is below power law trend")
            print("\n  ⚠️  IMPORTANT: This is a real-time estimate.")
            print("      Wait for daily close to confirm signal.")
        else:
            print("\n  🔴 NOT in double undervaluation buy zone")
            
            # Calculate what's needed
            if not dca_distance["in_zone"] and not trend_distance["in_zone"]:
                # Both need to drop
                max_drop_needed = max(dca_distance["percentage"], trend_distance["percentage"])
                print(f"\n  📉 To enter buy zone, BTC needs to drop ~{max_drop_needed:.2f}%")
                print(f"     (This assumes both conditions need to be met)")
            elif dca_distance["in_zone"] and not trend_distance["in_zone"]:
                # Only trend needs to drop
                print(f"\n  ✓ DCA condition already met")
                print(f"  📉 Need {trend_distance['percentage']:.2f}% more drop for trend condition")
            elif not dca_distance["in_zone"] and trend_distance["in_zone"]:
                # Only DCA needs to drop
                print(f"\n  ✓ Trend condition already met")
                print(f"  📉 Need {dca_distance['percentage']:.2f}% more drop for DCA condition")
        
        # ahr999 Index Analysis
        print("\n" + "=" * 80)
        print("📊 AHR999 INDEX ANALYSIS")
        print("=" * 80)
        
        print(f"\n  {ahr999_zone['emoji']} ahr999 Index:      {realtime_ahr999:.3f}")
        print(f"     Zone:               {ahr999_zone['label']}")
        print(f"     Action:             {ahr999_zone['action']}")
        print(f"     Description:        {ahr999_zone['description']}")
        
        if ahr999_percentile is not None:
            print(f"\n  📈 Historical Position:")
            print(f"     Overall Percentile:         {ahr999_percentile:.1f}th percentile (among all history)")
            
            # Interpret the overall percentile
            if ahr999_percentile < 10:
                interpretation = "🔥 EXCEPTIONAL - Only {:.1f}% of history was cheaper!".format(ahr999_percentile)
            elif ahr999_percentile < 25:
                interpretation = "💎 EXCELLENT - Only {:.1f}% of history was cheaper!".format(ahr999_percentile)
            elif ahr999_percentile < 50:
                interpretation = "✅ GOOD - Better than {:.0f}% of historical days".format(100 - ahr999_percentile)
            elif ahr999_percentile < 75:
                interpretation = "⚠️  FAIR - More expensive than {:.0f}% of history".format(ahr999_percentile)
            else:
                interpretation = "🔴 EXPENSIVE - More expensive than {:.0f}% of history".format(ahr999_percentile)
            
            print(f"     Interpretation:             {interpretation}")
            
            # Show buy zone percentile if applicable
            if ahr999_percentile_below_one is not None:
                print(f"\n     Buy Zone Percentile:        {ahr999_percentile_below_one:.1f}th percentile (among days with ahr999 < 1.0)")
                
                # Interpret buy zone percentile
                if ahr999_percentile_below_one < 10:
                    bz_interpretation = "🔥 Top 10% buying opportunity among buy zone days!"
                elif ahr999_percentile_below_one < 25:
                    bz_interpretation = "💎 Top 25% opportunity among buy zone days"
                elif ahr999_percentile_below_one < 50:
                    bz_interpretation = "✅ Better than average among buy zone days"
                else:
                    bz_interpretation = "⚠️  Below average among buy zone days"
                
                print(f"     Buy Zone Quality:           {bz_interpretation}")
            else:
                print(f"\n     Buy Zone Percentile:        N/A (ahr999 >= 1.0, not in buy zone)")
        
        print(f"\n  📚 Zone Thresholds:")
        print(f"     < 0.45  = 🔥 Bottom Zone (exceptional opportunity)")
        print(f"     < 1.2   = 💎 DCA Zone (good for accumulation)")
        print(f"     ≥ 1.2   = ⚠️  Watch Zone (potentially overheated)")
        
        print("\n" + "=" * 80)
    
    return result


if __name__ == "__main__":
    # Quick test
    check_realtime_status()

