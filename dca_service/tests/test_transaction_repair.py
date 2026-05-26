from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from dca_service.models import DCATransaction
from dca_service.services.transaction_repair import repair_dca_misclassified_transactions


def _add_imported_manual_order(
    session: Session,
    *,
    order_id: int,
    trade_id: int,
    timestamp: datetime,
    amount_usd: float,
    price: float = 50000.0,
    notes: str = "Imported from Binance",
) -> DCATransaction:
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=amount_usd,
        btc_amount=amount_usd / price,
        price=price,
        ahr999=0.0,
        notes=notes,
        timestamp=timestamp,
        source="MANUAL",
        is_manual=True,
        binance_order_id=order_id,
        binance_trade_id=trade_id,
        fee_amount=0.01,
        fee_asset="USDC",
        executed_amount_usd=amount_usd,
        executed_amount_btc=amount_usd / price,
        avg_execution_price_usd=price,
    )
    session.add(tx)
    return tx


def _seed_daily_imported_manual_orders(session: Session, *, start_order_id: int = 7000) -> list[int]:
    order_ids = []
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    amounts = [20.0, 20.1, 19.9, 20.2, 19.8, 20.0]
    for idx, amount in enumerate(amounts):
        order_id = start_order_id + idx
        order_ids.append(order_id)
        _add_imported_manual_order(
            session,
            order_id=order_id,
            trade_id=9000 + idx,
            timestamp=start + timedelta(days=idx),
            amount_usd=amount,
        )
    session.commit()
    return order_ids


def test_repair_dca_classification_dry_run_identifies_daily_imported_orders(session: Session):
    candidate_order_ids = _seed_daily_imported_manual_orders(session)
    random_manual = _add_imported_manual_order(
        session,
        order_id=9999,
        trade_id=9999,
        timestamp=datetime(2026, 1, 3, 14, 37, tzinfo=timezone.utc),
        amount_usd=150.0,
    )
    session.commit()

    result = repair_dca_misclassified_transactions(session, dry_run=True)

    assert result["dry_run"] is True
    assert result["candidate_order_count"] == len(candidate_order_ids)
    assert result["updated_row_count"] == 0
    assert {order["order_id"] for order in result["candidate_orders"]} == set(candidate_order_ids)
    assert all("minute_bucket=00:00" in order["reason"] for order in result["candidate_orders"])

    rows = session.exec(select(DCATransaction)).all()
    assert all(tx.source == "MANUAL" and tx.is_manual is True for tx in rows)
    assert random_manual.binance_order_id not in {order["order_id"] for order in result["candidate_orders"]}


def test_repair_dca_classification_apply_updates_only_candidates(session: Session):
    candidate_order_ids = _seed_daily_imported_manual_orders(session)
    _add_imported_manual_order(
        session,
        order_id=9999,
        trade_id=9999,
        timestamp=datetime(2026, 1, 3, 14, 37, tzinfo=timezone.utc),
        amount_usd=150.0,
    )
    session.commit()

    result = repair_dca_misclassified_transactions(session, dry_run=False)

    assert result["dry_run"] is False
    assert result["candidate_order_count"] == len(candidate_order_ids)
    assert result["updated_row_count"] == len(candidate_order_ids)

    rows = session.exec(select(DCATransaction)).all()
    by_order_id = {tx.binance_order_id: tx for tx in rows}
    for order_id in candidate_order_ids:
        assert by_order_id[order_id].source == "DCA"
        assert by_order_id[order_id].is_manual is False
        assert by_order_id[order_id].notes == "Imported from Binance"

    assert by_order_id[9999].source == "MANUAL"
    assert by_order_id[9999].is_manual is True


def test_repair_dca_classification_accepts_variable_daily_dca_amounts(session: Session):
    start = datetime(2025, 11, 28, 0, 0, tzinfo=timezone.utc)
    amounts = [12.0, 16.0, 20.0, 25.0, 30.0, 40.0]
    order_ids = []
    for idx, amount in enumerate(amounts):
        order_id = 8200 + idx
        order_ids.append(order_id)
        _add_imported_manual_order(
            session,
            order_id=order_id,
            trade_id=10200 + idx,
            timestamp=start + timedelta(days=idx),
            amount_usd=amount,
        )
    session.commit()

    result = repair_dca_misclassified_transactions(session, dry_run=True)

    assert result["candidate_order_count"] == len(order_ids)
    assert {order["order_id"] for order in result["candidate_orders"]} == set(order_ids)
    assert all("minute_bucket=00:00" in order["reason"] for order in result["candidate_orders"])


def test_repair_dca_classification_ignores_inconsistent_manual_buys(session: Session):
    start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    for idx, amount in enumerate([20.0, 80.0, 25.0, 140.0, 30.0]):
        _add_imported_manual_order(
            session,
            order_id=8000 + idx,
            trade_id=10000 + idx,
            timestamp=start + timedelta(days=idx),
            amount_usd=amount,
        )
    session.commit()

    result = repair_dca_misclassified_transactions(session, dry_run=False)

    assert result["candidate_order_count"] == 0
    assert result["updated_row_count"] == 0
    rows = session.exec(select(DCATransaction)).all()
    assert all(tx.source == "MANUAL" and tx.is_manual is True for tx in rows)


def test_repair_dca_classification_requires_imported_note_marker(session: Session):
    start = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    for idx in range(6):
        _add_imported_manual_order(
            session,
            order_id=8100 + idx,
            trade_id=10100 + idx,
            timestamp=start + timedelta(days=idx),
            amount_usd=20.0,
            notes="",
        )
    session.commit()

    result = repair_dca_misclassified_transactions(session, dry_run=False)

    assert result["candidate_order_count"] == 0
    assert result["updated_row_count"] == 0
    rows = session.exec(select(DCATransaction)).all()
    assert all(tx.source == "MANUAL" and tx.is_manual is True for tx in rows)


def test_repair_dca_classification_api_dry_run(client: TestClient, session: Session):
    _seed_daily_imported_manual_orders(session)

    response = client.post("/api/transactions/repair-dca-classification?dry_run=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["repair"]["dry_run"] is True
    assert payload["repair"]["candidate_order_count"] == 6
