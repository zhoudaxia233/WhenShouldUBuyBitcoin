#!/usr/bin/env python3
"""
Script to update the wealth distribution JSON data.
This script is intended to be run by GitHub Actions or manually.
"""
import json
import logging
import sys
from pathlib import Path
import requests
import pandas as pd
import io

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_and_update_data():
    url = "https://bitinfocharts.com/top-100-richest-bitcoin-addresses.html"
    output_path = Path("dca_service/src/dca_service/data/wealth_distribution.json")
    
    logger.info(f"Fetching data from {url}...")
    
    try:
        # Use standard requests with browser headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        logger.info("Parsing HTML tables...")
        # Wrap in StringIO to avoid FutureWarning
        tables = pd.read_html(io.StringIO(response.text))
        
        if not tables:
            raise ValueError("No tables found on page")
            
        # The wealth distribution table is usually the first one
        df = tables[0]
        
        # Basic validation to ensure it's the right table
        required_cols = ["Balance", "Addresses", "% Addresses (Total)", "Coins", "$USD", "% Coins (Total)", "% Coins (Total).1"]
        # Note: Column names might vary slightly, so we check for key keywords
        
        # Rename columns to match our schema
        # The table usually has: Balance, Addresses, % Addresses (Total), Coins, $USD, % Coins (Total)
        # We need to map these to our JSON structure
        
        # Clean up column names (remove .1, etc)
        df.columns = [c.replace('.1', '') for c in df.columns]
        
        logger.info(f"Found columns: {df.columns.tolist()}")
        
        distribution_data = []
        
        # Calculate cumulative percentile
        total_addresses = 0
        
        # First pass to get total addresses (if not available directly)
        # But the table usually has % Addresses, so we can infer or just use the row data
        
        # Let's parse the rows
        # We expect rows like: [0 - 0.001, 12345, ...]
        
        # We need to calculate the "Top X%" percentile for each tier
        # The table is usually sorted from smallest balance to largest, or vice versa
        # BitInfoCharts table is usually:
        # [0 - 0.001 BTC]
        # [0.001 - 0.01 BTC]
        # ...
        # [100,000 - 1,000,000 BTC]
        
        # We need to process it carefully.
        # Let's look at the structure we expect in JSON:
        # tier, balance, addresses, coins, usd, percent_coins, percentile
        
        # We will iterate through the dataframe
        # Note: The dataframe might contain a "Total" row at the bottom
        
        # Convert to list of dicts
        raw_data = df.to_dict('records')
        
        # Sort by balance tier to ensure correct percentile calculation
        # But parsing the tier string is hard.
        # Let's rely on the order if possible, or just extract what we need.
        
        # Actually, let's just extract the raw data and let the API calculate the percentile logic if needed?
        # No, the API expects "percentile" field.
        
        # Let's try to parse the "Top X%" if it exists, or calculate it.
        # BitInfoCharts doesn't explicitly give "Top X%" for every row in a simple column.
        # Wait, the previous scraper logic was:
        # tables = pd.read_html(url)
        # ...
        # It seems we were just dumping the table.
        
        # Let's look at the static data we just created to see the target format.
        # It has "percentile": "Top 0.00001%"
        
        # We need to calculate this.
        # Percentile = (Cumulative Addresses from Top / Total Addresses) * 100
        
        # Let's extract numeric addresses
        parsed_rows = []
        total_addr_count = 0
        
        for row in raw_data:
            # Skip total row
            # Check various keys for Balance
            tier = str(row.get('Balance', '') or row.get('Balance, BTC', ''))
            if tier.lower() == 'total' or not tier:
                continue
                
            # Extract exact values from the website without modification
            addresses_str = str(row.get('Addresses', '0'))
            coins_str = str(row.get('Coins', '') or row.get('BTC', '0'))
            usd_str = str(row.get('$USD', '') or row.get('USD', '0'))
            percent_coins = str(row.get('% Coins (Total)', '') or row.get('% BTC (Total)', '0%'))
            
            # Get the % Addresses (Total) which contains the percentile info
            percent_addrs_str = str(row.get('% Addresses (Total)', ''))
            
            # Clean address count for sorting
            try:
                addr_count = int(addresses_str.replace(',', '').split()[0])
            except:
                addr_count = 0
            
            parsed_rows.append({
                'tier': tier,
                'balance': tier,
                'addresses': addresses_str,
                'coins': coins_str,
                'usd': usd_str,
                'percent_coins': percent_coins,
                'percent_addresses': percent_addrs_str,  # Preserve exact value from website
                'addr_count_numeric': addr_count
            })
            
            total_addr_count += addr_count
            
        # Sort from Richest to Poorest (highest BTC tiers first)
        def parse_min_btc(tier_str):
            try:
                clean = tier_str.replace('[', '').replace('(', '').replace(',', '')
                parts = clean.split('-')
                return float(parts[0])
            except:
                return -1
                
        parsed_rows.sort(key=lambda x: parse_min_btc(x['tier']), reverse=True)
        
        # Extract the percentile from the data - the website already has this information
        # in the % Addresses (Total) column format like "0.00001% (0.00001%)"
        # The value in parentheses is the cumulative percentile
        final_data = []
        
        for row in parsed_rows:
            # Parse the cumulative percentile from the percent_addresses field
            # Format: "X.XX% (Y.YY%)" where Y.YY is the cumulative "Top Y.YY%"
            percent_addr = row['percent_addresses']
            
            # Extract the cumulative percentage (the value in parentheses)
            try:
                if '(' in percent_addr:
                    # Extract "Y.YY%" from "X.XX% (Y.YY%)"
                    cumulative = percent_addr.split('(')[1].split(')')[0].strip()
                    percentile_str = f"Top {cumulative}"
                else:
                    percentile_str = f"Top {percent_addr}"
            except:
                # Fallback if parsing fails
                percentile_str = f"Top {percent_addr}"
            
            # Construct final dict with exact data from website
            item = {
                "tier": row['tier'],
                "balance": row['balance'],
                "addresses": row['addresses'],
                "coins": row['coins'],
                "usd": row['usd'],
                "percent_coins": row['percent_coins'],
                "percentile": percentile_str
            }
            final_data.append(item)
            
        logger.info(f"Processed {len(final_data)} rows.")
        
        # Write to JSON
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(final_data, f, indent=2)
            
        logger.info(f"Successfully updated {output_path}")
        
    except Exception as e:
        logger.error(f"Failed to update data: {e}")
        sys.exit(1)

if __name__ == "__main__":
    fetch_and_update_data()
