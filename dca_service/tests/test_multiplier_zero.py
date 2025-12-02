"""
Tests for multiplier=0 behavior in DCA engine.

Verifies that:
1. When multiplier is set to 0, DCA execution is prevented
2. When multiplier is > 0, DCA execution is allowed
3. All tiers with multiplier=0 prevent execution
4. Dynamic strategy respects min_multiplier=0
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlmodel import Session, select

from dca_service.models import DCAStrategy
from dca_service.services.dca_engine import calculate_dca_decision


class TestMultiplierZeroBehavior:
    """Tests to ensure multiplier=0 correctly prevents DCA execution"""
    
    def test_multiplier_zero_prevents_execution(self, session: Session):
        """
        Test that multiplier=0 prevents DCA execution.
        
        Scenario:
        1. Setup AHR999 percentile strategy
        2. Set multiplier_p50 = 0 (cheap tier)
        3. Mock AHR999 to fall in p50 range (0.60 - 0.90)
        4. Verify: can_execute = False
        5. Verify: reason mentions "Multiplier is 0"
        """
        # Create strategy with multiplier_p50 = 0
        strategy = DCAStrategy(
            is_active=True,
            total_budget_usd=1000.0,
            target_btc_amount=1.0,
            strategy_type="ahr999_percentile",
            execution_frequency="daily",
            execution_time_utc="12:00",
            execution_mode="DRY_RUN",
            # Legacy multipliers (required by schema, even for percentile strategy)
            ahr999_multiplier_low=5.0,
            ahr999_multiplier_mid=2.0,
            ahr999_multiplier_high=0.0,
            # Set p50 multiplier to 0
            ahr999_multiplier_p10=5.0,
            ahr999_multiplier_p25=2.0,
            ahr999_multiplier_p50=0.0,  # ZERO - should prevent execution
            ahr999_multiplier_p75=0.0,
            ahr999_multiplier_p90=0.0,
            ahr999_multiplier_p100=0.0,
            enforce_monthly_cap=True
        )
        session.add(strategy)
        session.commit()
        
        # Mock get_latest_metrics to return AHR999 in p50 range (0.60 - 0.90)
        mock_metrics = {
            "price_usd": 85000.0,
            "ahr999": 0.75,  # Falls in p50 range (cheap)
            "peak180": 90000.0,
            "source": "test",
            "source_label": "Test Data"
        }
        
        # Mock percentile thresholds
        mock_percentiles = {
            "p10": 0.45,
            "p25": 0.60,
            "p50": 0.90,
            "p75": 1.20,
            "p90": 1.80
        }
        
        with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics), \
             patch("dca_service.services.dca_engine.calculate_ahr999_percentile_thresholds", return_value=mock_percentiles):
            
            decision = calculate_dca_decision(session)
        
        # Verify execution is prevented
        assert decision.can_execute is False, "Should not execute when multiplier=0"
        assert "Multiplier is 0" in decision.reason, f"Reason should mention multiplier=0, got: {decision.reason}"
        assert decision.multiplier == 0.0, "Multiplier should be 0"
        assert decision.ahr_band == "p50", "Should correctly identify p50 band"
        assert decision.suggested_amount_usd == 0.0, "Suggested amount should be 0"
    
    def test_multiplier_nonzero_allows_execution(self, session: Session):
        """
        Test that multiplier > 0 allows DCA execution.
        
        Scenario:
        1. Setup strategy with multiplier_p50 = 1.5
        2. Mock AHR999 to fall in p50 range
        3. Verify: can_execute = True
        4. Verify: suggested_amount = base_amount * 1.5
        """
        # Create strategy with multiplier_p50 = 1.5
        strategy = DCAStrategy(
            is_active=True,
            total_budget_usd=1000.0,
            target_btc_amount=1.0,
            strategy_type="ahr999_percentile",
            execution_frequency="daily",
            execution_time_utc="12:00",
            execution_mode="DRY_RUN",
            # Legacy multipliers (required by schema)
            ahr999_multiplier_low=5.0,
            ahr999_multiplier_mid=2.0,
            ahr999_multiplier_high=0.5,
            # Percentile multipliers
            ahr999_multiplier_p10=5.0,
            ahr999_multiplier_p25=2.0,
            ahr999_multiplier_p50=1.5,  # Non-zero
            ahr999_multiplier_p75=0.5,
            ahr999_multiplier_p90=0.0,
            ahr999_multiplier_p100=0.0,
            enforce_monthly_cap=True
        )
        session.add(strategy)
        session.commit()
        
        # Mock metrics
        mock_metrics = {
            "price_usd": 85000.0,
            "ahr999": 0.75,  # Falls in p50 range
            "peak180": 90000.0,
            "source": "test",
            "source_label": "Test Data"
        }
        
        mock_percentiles = {
            "p10": 0.45,
            "p25": 0.60,
            "p50": 0.90,
            "p75": 1.20,
            "p90": 1.80
        }
        
        with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics), \
             patch("dca_service.services.dca_engine.calculate_ahr999_percentile_thresholds", return_value=mock_percentiles):
            
            decision = calculate_dca_decision(session)
        
        # Verify execution is allowed
        assert decision.can_execute is True, "Should execute when multiplier > 0"
        assert decision.multiplier == 1.5, "Multiplier should be 1.5"
        assert decision.ahr_band == "p50", "Should identify p50 band"
        
        # Calculate expected amounts
        base_amount = 1000.0 / 30.44  # Daily frequency
        expected_amount = base_amount * 1.5
        
        assert abs(decision.suggested_amount_usd - expected_amount) < 0.01, \
            f"Suggested amount should be base * multiplier, expected {expected_amount}, got {decision.suggested_amount_usd}"
    
    def test_all_multipliers_zero(self, session: Session):
        """
        Test that all tiers with multiplier=0 prevent execution.
        
        Scenario:
        1. Set all 6 tier multipliers to 0
        2. Test AHR999 in each tier range
        3. Verify: All return can_execute = False
        """
        # Create strategy with all multipliers = 0
        strategy = DCAStrategy(
            is_active=True,
            total_budget_usd=1000.0,
            target_btc_amount=1.0,
            strategy_type="ahr999_percentile",
            execution_frequency="daily",
            execution_time_utc="12:00",
            execution_mode="DRY_RUN",
            # Legacy multipliers (required by schema)
            ahr999_multiplier_low=0.0,
            ahr999_multiplier_mid=0.0,
            ahr999_multiplier_high=0.0,
            # All percentile multipliers set to 0
            ahr999_multiplier_p10=0.0,
            ahr999_multiplier_p25=0.0,
            ahr999_multiplier_p50=0.0,
            ahr999_multiplier_p75=0.0,
            ahr999_multiplier_p90=0.0,
            ahr999_multiplier_p100=0.0,
            enforce_monthly_cap=True
        )
        session.add(strategy)
        session.commit()
        
        mock_percentiles = {
            "p10": 0.45,
            "p25": 0.60,
            "p50": 0.90,
            "p75": 1.20,
            "p90": 1.80
        }
        
        # Test each tier
        test_cases = [
            (0.30, "p10"),   # Below p10
            (0.50, "p25"),   # Between p10 and p25
            (0.75, "p50"),   # Between p25 and p50
            (1.00, "p75"),   # Between p50 and p75
            (1.50, "p90"),   # Between p75 and p90
            (2.00, "p100"),  # Above p90
        ]
        
        for ahr999_value, expected_band in test_cases:
            mock_metrics = {
                "price_usd": 85000.0,
                "ahr999": ahr999_value,
                "peak180": 90000.0,
                "source": "test",
                "source_label": "Test Data"
            }
            
            with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics), \
                 patch("dca_service.services.dca_engine.calculate_ahr999_percentile_thresholds", return_value=mock_percentiles):
                
                decision = calculate_dca_decision(session)
            
            assert decision.can_execute is False, \
                f"AHR999={ahr999_value} in {expected_band} should not execute with multiplier=0"
            assert "Multiplier is 0" in decision.reason, \
                f"Reason should mention multiplier=0 for {expected_band}"
            assert decision.ahr_band == expected_band, \
                f"Should correctly identify {expected_band} band"
            assert decision.multiplier == 0.0, \
                f"Multiplier should be 0 for {expected_band}"
    
    def test_legacy_strategy_multiplier_zero(self, session: Session):
        """
        Test that legacy AHR999 strategy also respects multiplier=0.
        
        Scenario:
        1. Use legacy strategy type
        2. Set ahr999_multiplier_high = 0 (expensive zone)
        3. Mock AHR999 > 1.2 (high zone)
        4. Verify: can_execute = False
        """
        # Create legacy strategy
        strategy = DCAStrategy(
            is_active=True,
            total_budget_usd=1000.0,
            target_btc_amount=1.0,
            strategy_type="ahr999",  # Legacy type
            execution_frequency="daily",
            execution_time_utc="12:00",
            execution_mode="DRY_RUN",
            # Legacy multipliers
            ahr999_multiplier_low=5.0,
            ahr999_multiplier_mid=2.0,
            ahr999_multiplier_high=0.0,  # ZERO - should prevent execution when expensive
            enforce_monthly_cap=True
        )
        session.add(strategy)
        session.commit()
        
        # Mock metrics with high AHR999 (expensive)
        mock_metrics = {
            "price_usd": 95000.0,
            "ahr999": 1.5,  # High (> 1.2)
            "peak180": 100000.0,
            "source": "test",
            "source_label": "Test Data"
        }
        
        with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics):
            decision = calculate_dca_decision(session)
        
        # Verify execution is prevented
        assert decision.can_execute is False, \
            "Legacy strategy should not execute when multiplier_high=0"
        assert "Multiplier is 0" in decision.reason, \
            f"Reason should mention multiplier=0, got: {decision.reason}"
        assert decision.multiplier == 0.0, "Multiplier should be 0"
