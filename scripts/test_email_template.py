import sys
import logging
from datetime import datetime, timezone
from sqlmodel import Session, select
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append("dca_service/src")

from dca_service.database import engine
from dca_service.models import DCATransaction, GlobalSettings
from dca_service.services.mailer import send_dca_notification
from dca_service.services.dca_engine import DCADecision

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_email_template():
    """
    Test the email template generation by mocking the send_email function.
    """
    print("Testing Email Template Generation...")
    
    # Mock transaction
    transaction = DCATransaction(
        id=123,
        timestamp=datetime.now(timezone.utc),
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.00123456,
        price=81000.0,
        ahr999_value=0.45,
        source="SIMULATED",
        notes="Test transaction"
    )
    
    # Mock decision
    decision = MagicMock(spec=DCADecision)
    decision.ahr_band = "p10 (EXTREME CHEAP)"
    decision.band = "p10" # Fallback check
    
    # Mock database session for stats
    # We need to mock _get_goal_progress to avoid DB/Network calls
    # We don't need to mock _get_total_btc_balance if we pass total_btc explicitly
    with patch("dca_service.services.mailer._get_goal_progress") as mock_progress, \
         patch("dca_service.services.mailer.send_email") as mock_send:
        
        mock_progress.return_value = "1.5000 / 2.0000 BTC (75.00%)"
        
        # Call the function with explicit total_btc
        # This simulates the new behavior where the caller fetches the correct balance
        send_dca_notification(transaction, decision, total_btc=1.5)
        
        # Verify
        if mock_send.called:
            args, _ = mock_send.call_args
            subject = args[0]
            body = args[1]
            
            print("\n✅ Email Sent (Mocked)")
            print(f"Subject: {subject}")
            print("-" * 40)
            print(body)
            print("-" * 40)
            
            # Assertions
            assert "Transaction ID" not in body, "Transaction ID should be removed"
            assert "Source:" not in body, "Source should be removed"
            assert "Status:" not in body, "Status should be removed"
            assert "Decision Band: p10 (EXTREME CHEAP)" in body, "Decision band incorrect"
            assert "Total BTC Balance: 1.50000000 BTC" in body, "Total BTC missing or incorrect"
            assert "Goal Progress: 1.5000 / 2.0000 BTC (75.00%)" in body, "Goal Progress missing"
            
            print("\n✅ All checks passed!")
        else:
            print("\n❌ Email was not sent!")

if __name__ == "__main__":
    test_email_template()
