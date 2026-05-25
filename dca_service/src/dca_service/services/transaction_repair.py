from __future__ import annotations

from datetime import datetime, timezone
from statistics import median, pstdev
from typing import Any, Dict, List

from sqlmodel import Session, select

from dca_service.models import DCATransaction


MIN_ORDERS_PER_BUCKET = 5
MIN_DISTINCT_DATES = 4
MAX_AMOUNT_CV = 0.35
MIN_DAILY_GAP_RATIO = 0.60


def _effective_usd(tx: DCATransaction) -> float:
    return float(tx.executed_amount_usd or tx.fiat_amount or 0.0)


def _effective_btc(tx: DCATransaction) -> float:
    return float(tx.executed_amount_btc or tx.btc_amount or 0.0)


def _normalized_timestamp(tx: DCATransaction) -> datetime:
    timestamp = tx.timestamp
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _is_imported_manual_candidate(tx: DCATransaction) -> bool:
    if tx.status != "SUCCESS":
        return False
    if tx.binance_order_id is None:
        return False
    if (tx.source or "").upper() != "MANUAL":
        return False
    if not bool(tx.is_manual):
        return False
    if _effective_usd(tx) <= 0 or _effective_btc(tx) <= 0:
        return False

    note = (tx.notes or "").strip().lower()
    return note == "imported from binance"


def _amount_cv(amounts: List[float]) -> float:
    if not amounts:
        return 0.0
    mean_amount = sum(amounts) / len(amounts)
    if mean_amount <= 0:
        return 0.0
    return float(pstdev(amounts) / mean_amount)


def _daily_gap_stats(dates: List[Any]) -> Dict[str, Any]:
    sorted_dates = sorted(set(dates))
    gaps = [(sorted_dates[idx] - sorted_dates[idx - 1]).days for idx in range(1, len(sorted_dates))]
    if not gaps:
        return {
            "median_gap_days": None,
            "daily_gap_ratio": 0.0,
            "gap_count": 0,
        }
    one_day_gaps = sum(1 for gap in gaps if gap == 1)
    return {
        "median_gap_days": float(median(gaps)),
        "daily_gap_ratio": float(one_day_gaps / len(gaps)),
        "gap_count": len(gaps),
    }


def _group_candidate_orders(rows: List[DCATransaction]) -> List[Dict[str, Any]]:
    grouped: Dict[int, Dict[str, Any]] = {}
    for tx in rows:
        if not _is_imported_manual_candidate(tx):
            continue
        order_id = int(tx.binance_order_id)
        timestamp = _normalized_timestamp(tx)
        group = grouped.setdefault(
            order_id,
            {
                "order_id": order_id,
                "timestamp": timestamp,
                "amount_usd": 0.0,
                "amount_btc": 0.0,
                "row_ids": [],
                "trade_ids": [],
            },
        )
        group["timestamp"] = min(group["timestamp"], timestamp)
        group["amount_usd"] += _effective_usd(tx)
        group["amount_btc"] += _effective_btc(tx)
        if tx.id is not None:
            group["row_ids"].append(int(tx.id))
        if tx.binance_trade_id is not None:
            group["trade_ids"].append(int(tx.binance_trade_id))

    return sorted(grouped.values(), key=lambda item: item["timestamp"])


def _find_repair_candidates(order_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for order in order_groups:
        minute_bucket = order["timestamp"].strftime("%H:%M")
        buckets.setdefault(minute_bucket, []).append(order)

    candidates: List[Dict[str, Any]] = []
    for minute_bucket, bucket_orders in buckets.items():
        dates = [order["timestamp"].date() for order in bucket_orders]
        amounts = [float(order["amount_usd"]) for order in bucket_orders]
        gap_stats = _daily_gap_stats(dates)
        amount_cv = _amount_cv(amounts)

        enough_orders = len(bucket_orders) >= MIN_ORDERS_PER_BUCKET
        enough_dates = len(set(dates)) >= MIN_DISTINCT_DATES
        median_gap_days = gap_stats["median_gap_days"]
        median_gap_ok = median_gap_days is not None and 0.8 <= median_gap_days <= 1.3
        daily_gap_ok = gap_stats["daily_gap_ratio"] >= MIN_DAILY_GAP_RATIO
        amount_ok = amount_cv <= MAX_AMOUNT_CV

        if not (enough_orders and enough_dates and (median_gap_ok or daily_gap_ok) and amount_ok):
            continue

        reason = (
            f"minute_bucket={minute_bucket}; orders={len(bucket_orders)}; "
            f"distinct_dates={len(set(dates))}; median_gap_days={median_gap_days}; "
            f"daily_gap_ratio={gap_stats['daily_gap_ratio']:.2f}; amount_cv={amount_cv:.3f}"
        )
        for order in bucket_orders:
            candidates.append(
                {
                    "order_id": order["order_id"],
                    "purchased_at": order["timestamp"].isoformat(),
                    "amount_usd": float(order["amount_usd"]),
                    "amount_btc": float(order["amount_btc"]),
                    "row_ids": order["row_ids"],
                    "trade_ids": sorted(order["trade_ids"]),
                    "minute_bucket": minute_bucket,
                    "reason": reason,
                }
            )

    return sorted(candidates, key=lambda item: item["purchased_at"])


def repair_dca_misclassified_transactions(session: Session, *, dry_run: bool) -> Dict[str, Any]:
    rows = session.exec(
        select(DCATransaction)
        .where(DCATransaction.status == "SUCCESS")
        .where(DCATransaction.binance_order_id.is_not(None))
        .order_by(DCATransaction.timestamp)
    ).all()

    order_groups = _group_candidate_orders(rows)
    candidate_orders = _find_repair_candidates(order_groups)
    candidate_order_ids = {int(order["order_id"]) for order in candidate_orders}
    candidate_row_count = sum(len(order["row_ids"]) for order in candidate_orders)

    updated_row_count = 0
    if not dry_run and candidate_order_ids:
        for tx in rows:
            if tx.binance_order_id is None or int(tx.binance_order_id) not in candidate_order_ids:
                continue
            if not _is_imported_manual_candidate(tx):
                continue
            tx.source = "DCA"
            tx.is_manual = False
            session.add(tx)
            updated_row_count += 1
        session.commit()

    return {
        "dry_run": bool(dry_run),
        "scanned_order_count": len(order_groups),
        "candidate_order_count": len(candidate_orders),
        "candidate_row_count": candidate_row_count,
        "updated_row_count": updated_row_count,
        "candidate_orders": candidate_orders,
    }
