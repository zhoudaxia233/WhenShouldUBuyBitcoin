#!/usr/bin/env python3
"""
Data cleanup script to remove duplicate DCA transactions.

This script identifies and removes MANUAL transactions that are duplicates of DCA transactions
(same binance_order_id, but different source).

⚠️  WARNING: This script modifies your database. Back up your database before running!

Usage:
    poetry run python scripts/cleanup_duplicate_dca.py --dry-run  # Preview changes
    poetry run python scripts/cleanup_duplicate_dca.py             # Execute cleanup
"""

import argparse
from sqlmodel import Session, select, create_engine
from typing import List, Tuple

# Import from dca_service
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "dca_service" / "src"))

from dca_service.models import DCATransaction
from dca_service.config import settings


def find_duplicates(session: Session) -> List[Tuple[str, List[DCATransaction]]]:
    """
    Find transactions with duplicate binance_order_id but different sources.
    
    Returns:
        List of (binance_order_id, [transactions]) tuples
    """
    # Get all transactions with binance_order_id
    all_txs = session.exec(
        select(DCATransaction)
        .where(DCATransaction.binance_order_id.is_not(None))
        .order_by(DCATransaction.binance_order_id, DCATransaction.timestamp)
    ).all()
    
    # Group by binance_order_id
    order_groups = {}
    for tx in all_txs:
        order_id = tx.binance_order_id
        if order_id not in order_groups:
            order_groups[order_id] = []
        order_groups[order_id].append(tx)
    
    # Find duplicates (where count > 1 and sources differ)
    duplicates = []
    for order_id, txs in order_groups.items():
        if len(txs) > 1:
            sources = {tx.source for tx in txs}
            if len(sources) > 1:  # Different sources = duplicate
                duplicates.append((order_id, txs))
    
    return duplicates


def cleanup_duplicates(session: Session, dry_run: bool = True) -> int:
    """
    Remove duplicate MANUAL transactions, keeping DCA/BINANCE transactions.
    
    Args:
        session: Database session
        dry_run: If True, only print what would be deleted
        
    Returns:
        Number of transactions deleted (or would be deleted in dry-run)
    """
    duplicates = find_duplicates(session)
    
    if not duplicates:
        print("✅ No duplicates found!")
        return 0
    
    print(f"\n Found {len(duplicates)} order(s) with duplicate transactions:\n")
    
    deleted_count = 0
    
    for order_id, txs in duplicates:
        print(f"Order ID: {order_id}")
        print(f"  Transactions: {len(txs)}")
        
        # Separate by source
        dca_txs = [tx for tx in txs if tx.source in ["DCA", "BINANCE"]]
        manual_txs = [tx for tx in txs if tx.source == "MANUAL"]
        simulated_txs = [tx for tx in txs if tx.source == "SIMULATED"]
        
        print(f"    - DCA/BINANCE: {len(dca_txs)}")
        print(f"    - MANUAL: {len(manual_txs)}")
        print(f"    - SIMULATED: {len(simulated_txs)}")
        
        # Strategy: Keep DCA/BINANCE, remove MANUAL duplicates
        if dca_txs and manual_txs:
            print(f"  🔧 Will delete {len(manual_txs)} MANUAL transaction(s):")
            for tx in manual_txs:
                print(f"     - ID {tx.id}: {tx.source}, {tx.btc_amount:.8f} BTC @ ${tx.price:.2f}, {tx.timestamp}")
                
                if not dry_run:
                    session.delete(tx)
                    deleted_count += 1
                else:
                    deleted_count += 1  # Count for dry-run
        
        print()
    
    if not dry_run:
        session.commit()
        print(f"✅ Deleted {deleted_count} duplicate MANUAL transaction(s)")
    else:
        print(f"🔍 DRY RUN: Would delete {deleted_count} duplicate MANUAL transaction(s)")
        print("   Run without --dry-run to execute cleanup")
    
    return deleted_count


def main():
    parser = argparse.ArgumentParser(
        description="Clean up duplicate DCA transactions",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying database"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("DCA Transaction Duplicate Cleanup")
    print("=" * 60)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made\n")
    else:
        print("⚠️  LIVE MODE - Database will be modified!")
        print("   Make sure you have a backup!\n")
        response = input("Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            return
    
    # Connect to database
    db_url = settings.DATABASE_URL
    engine = create_engine(db_url)
    
    with Session(engine) as session:
        cleanup_duplicates(session, dry_run=args.dry_run)
    
    print("\n" + "=" * 60)
    print("Cleanup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
