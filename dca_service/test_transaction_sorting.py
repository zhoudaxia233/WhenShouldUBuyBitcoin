import sys
import os
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

# Add src to path
sys.path.append(os.path.abspath("src"))

from dca_service.main import app
from dca_service.database import create_db_and_tables

# Create tables
create_db_and_tables()

client = TestClient(app)

def test_transaction_sorting_with_cold_wallet():
    """
    Test that transactions are sorted by timestamp regardless of source.
    
    This test verifies the fix for the bug where cold wallet entries
    with Germany timezone were incorrectly appearing at the top of
    the transaction list.
    """
    print("\n=== Test: Transaction Sorting with Cold Wallet ===\n")
    
    # 1. Create a simulated DCA transaction (will get current timestamp)
    print("Step 1: Creating simulated DCA transaction...")
    response1 = client.post("/api/transactions/simulate", json={
        "fiat_amount": 100.0,
        "ahr999": 0.5,
        "price": 50000.0,
        "notes": "First simulated transaction"
    })
    assert response1.status_code == 200, f"Failed to create DCA transaction: {response1.text}"
    dca_tx1 = response1.json()
    dca_timestamp1 = datetime.fromisoformat(dca_tx1["timestamp"].replace("Z", "+00:00"))
    print(f"   Created DCA transaction at: {dca_timestamp1}")
    
    # 2. Create a cold wallet entry with timestamp 1 minute later
    print("\nStep 2: Creating cold wallet entry (1 minute later)...")
    future_time = datetime.now(timezone.utc) + timedelta(minutes=1)
    future_time_iso = future_time.isoformat()
    
    response2 = client.post("/api/cold_wallet", json={
        "btc_amount": 0.5,
        "fee_btc": 0.0001,
        "notes": "Cold wallet entry",
        "timestamp": future_time_iso
    })
    assert response2.status_code == 200, f"Failed to create cold wallet entry: {response2.text}"
    cold_wallet_entry = response2.json()
    cold_wallet_timestamp = datetime.fromisoformat(cold_wallet_entry["timestamp"].replace("Z", "+00:00"))
    print(f"   Created cold wallet entry at: {cold_wallet_timestamp}")
    
    # 3. Create another simulated DCA transaction (2 minutes later)
    print("\nStep 3: Creating another simulated DCA transaction (most recent)...")
    import time
    time.sleep(0.1)  # Small delay to ensure different timestamp
    response3 = client.post("/api/transactions/simulate", json={
        "fiat_amount": 100.0,
        "ahr999": 0.5,
        "price": 51000.0,
        "notes": "Second simulated transaction (most recent)"
    })
    assert response3.status_code == 200, f"Failed to create second DCA transaction: {response3.text}"
    dca_tx2 = response3.json()
    dca_timestamp2 = datetime.fromisoformat(dca_tx2["timestamp"].replace("Z", "+00:00"))
    print(f"   Created DCA transaction at: {dca_timestamp2}")
    
    # 4. Fetch transactions and verify sorting
    print("\nStep 4: Fetching all transactions...")
    response4 = client.get("/api/transactions?limit=50")
    assert response4.status_code == 200, f"Failed to fetch transactions: {response4.text}"
    transactions = response4.json()
    
    print(f"\n   Total transactions: {len(transactions)}")
    print("\n   Top 3 transactions (should be in descending order by timestamp):")
    for i, tx in enumerate(transactions[:3]):
        tx_time = datetime.fromisoformat(tx["timestamp"].replace("Z", "+00:00"))
        print(f"   {i+1}. {tx['type']:8} | {tx['id']:12} | {tx_time} | {tx.get('notes', 'N/A')}")
    
    # 5. Verify sorting
    print("\nStep 5: Verifying transaction order...")
    
    # The most recent transaction should be first (which should be the cold wallet entry since it's 1 minute in the future)
    first_tx = transactions[0]
    first_timestamp = datetime.fromisoformat(first_tx["timestamp"].replace("Z", "+00:00"))
    
    print(f"   First transaction timestamp: {first_timestamp}")
    print(f"   DCA TX 2 timestamp:          {dca_timestamp2}")
    print(f"   Cold Wallet timestamp:       {cold_wallet_timestamp}")
    print(f"   DCA TX 1 timestamp:          {dca_timestamp1}")
    
    # The cold wallet should be first since it's the most recent
    assert first_tx["type"] == "MANUAL", "Most recent transaction (cold wallet) should be first"
    assert first_timestamp == cold_wallet_timestamp, "Timestamps don't match"
    
    # Verify timestamps are in descending order (most recent first)
    for i in range(len(transactions) - 1):
        current_time = datetime.fromisoformat(transactions[i]["timestamp"].replace("Z", "+00:00"))
        next_time = datetime.fromisoformat(transactions[i+1]["timestamp"].replace("Z", "+00:00"))
        assert current_time >= next_time, \
            f"Transactions not sorted! Position {i} ({current_time}) is before position {i+1} ({next_time})"
    
    print("\n✓ All transactions are correctly sorted by timestamp (descending)")
    print("✓ Most recent transaction appears at the top (cold wallet entry with future timestamp)")
    print("\n=== Test PASSED ===\n")


def test_timezone_conversion():
    """
    Test that Germany timezone is correctly converted to UTC.
    """
    print("\n=== Test: Timezone Conversion (Germany to UTC) ===\n")
    
    # Create a cold wallet entry with a known timestamp
    # Germany is UTC+1 in winter, UTC+2 in summer
    # Let's use a winter date: 2025-01-15 14:00 CET should be 13:00 UTC
    
    print("Test case: 2025-01-15 14:00 Germany time (winter, CET = UTC+1)")
    print("Expected UTC: 2025-01-15 13:00")
    
    # In the actual frontend, this would be done via JavaScript
    # Here we just verify the backend accepts and stores the UTC timestamp correctly
    
    response = client.post("/api/cold_wallet", json={
        "btc_amount": 0.001,
        "notes": "Timezone test entry",
        "timestamp": "2025-01-15T13:00:00Z"  # This is the expected UTC conversion
    })
    
    assert response.status_code == 200
    entry = response.json()
    stored_timestamp = entry["timestamp"]
    
    print(f"Stored timestamp: {stored_timestamp}")
    assert "2025-01-15T13:00:00" in stored_timestamp, "Timestamp not stored correctly"
    
    print("✓ UTC timestamp stored correctly")
    print("\n=== Test PASSED ===\n")


if __name__ == "__main__":
    try:
        test_transaction_sorting_with_cold_wallet()
        test_timezone_conversion()
        print("\n" + "="*60)
        print("ALL TESTS PASSED ✓")
        print("="*60 + "\n")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
