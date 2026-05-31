from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, col, delete
from datetime import timezone
from pathlib import Path

from dca_service.database import get_session
from dca_service.models import DCATransaction, BinanceCredentials, User
from dca_service.api.schemas import TransactionRead, UnifiedTransaction
from dca_service.services.binance_client import BinanceClient
from dca_service.services.security import decrypt_text
from dca_service.core.logging import logger
from dca_service.auth.dependencies import get_current_user, get_current_admin_user

router = APIRouter()
_static_generation_process = None
_static_generation_last_result = None
_static_generation_log_path = None


def _source_restore_priority(source: str | None) -> int:
    # Prefer app-originated records (DCA/BINANCE) over generic synced MANUAL rows.
    if source == "DCA":
        return 3
    if source == "BINANCE":
        return 2
    if source == "MANUAL":
        return 1
    return 0


def _transaction_display_source_and_type(tx: DCATransaction) -> tuple[str, str]:
    if tx.source == "SIMULATED":
        return "SIMULATED", "DCA"
    if tx.source == "DCA":
        return "DCA", "DCA"
    if tx.source == "BINANCE" and bool(tx.is_manual):
        return "EXTRA BUY", "MANUAL"
    if bool(tx.is_manual):
        return "MANUAL", "MANUAL"
    return "DCA", "DCA"


def _build_order_metadata_snapshot(session: Session) -> Dict[int, Dict[str, Any]]:
    """
    Snapshot metadata that Binance re-sync cannot reconstruct, keyed by order_id.

    This preserves semantic fields such as source / is_manual / ahr999 for orders
    that will be re-imported from Binance during Reset & Sync.
    """
    rows = session.exec(
        select(DCATransaction)
        .where(DCATransaction.binance_order_id.is_not(None))
        .order_by(col(DCATransaction.timestamp).asc(), col(DCATransaction.id).asc())
    ).all()

    snapshot: Dict[int, Dict[str, Any]] = {}
    for tx in rows:
        if tx.binance_order_id is None:
            continue
        order_id = int(tx.binance_order_id)
        existing = snapshot.get(order_id)
        candidate_priority = _source_restore_priority(tx.source)

        if existing is None:
            snapshot[order_id] = {
                "source": tx.source,
                "is_manual": bool(tx.is_manual),
                "ahr999": float(tx.ahr999 or 0.0),
                "notes": tx.notes,
                "timestamp": tx.timestamp,
                "intended_amount_usd": tx.intended_amount_usd,
                "row_count": 1,
                "sum_quote_usd": float(tx.executed_amount_usd or tx.fiat_amount or 0.0),
                "sum_btc": float(tx.executed_amount_btc or tx.btc_amount or 0.0),
                "sum_fee": float(tx.fee_amount or 0.0),
                "fee_assets": {tx.fee_asset} if tx.fee_asset else set(),
                "_priority": candidate_priority,
            }
            continue

        # Preserve the best semantic source classification.
        if candidate_priority > existing.get("_priority", -1):
            existing["source"] = tx.source
            existing["is_manual"] = bool(tx.is_manual)
            existing["notes"] = tx.notes
            existing["timestamp"] = tx.timestamp
            existing["intended_amount_usd"] = tx.intended_amount_usd
            existing["_priority"] = candidate_priority

        # Prefer a non-zero AHR999 if present in any prior row for this order.
        current_ahr = float(existing.get("ahr999") or 0.0)
        tx_ahr = float(tx.ahr999 or 0.0)
        if abs(current_ahr) < 1e-12 and abs(tx_ahr) >= 1e-12:
            existing["ahr999"] = tx_ahr

        # Prefer the earliest known timestamp if we have conflicting duplicates.
        current_ts = existing.get("timestamp")
        if current_ts is None or (tx.timestamp and tx.timestamp < current_ts):
            existing["timestamp"] = tx.timestamp

        if existing.get("notes") in (None, "", "Imported from Binance") and tx.notes:
            existing["notes"] = tx.notes

        if existing.get("intended_amount_usd") in (None, 0.0) and tx.intended_amount_usd:
            existing["intended_amount_usd"] = tx.intended_amount_usd

        existing["row_count"] = int(existing.get("row_count") or 0) + 1
        existing["sum_quote_usd"] = float(existing.get("sum_quote_usd") or 0.0) + float(tx.executed_amount_usd or tx.fiat_amount or 0.0)
        existing["sum_btc"] = float(existing.get("sum_btc") or 0.0) + float(tx.executed_amount_btc or tx.btc_amount or 0.0)
        existing["sum_fee"] = float(existing.get("sum_fee") or 0.0) + float(tx.fee_amount or 0.0)
        fee_assets = existing.get("fee_assets")
        if not isinstance(fee_assets, set):
            fee_assets = set(fee_assets or [])
        if tx.fee_asset:
            fee_assets.add(tx.fee_asset)
        existing["fee_assets"] = fee_assets

    for value in snapshot.values():
        value.pop("_priority", None)
    return snapshot


def _apply_preserved_order_metadata(tx: DCATransaction, metadata: Optional[Dict[str, Any]]) -> bool:
    if not metadata:
        return False
    tx.source = metadata.get("source", tx.source)
    if "is_manual" in metadata:
        tx.is_manual = bool(metadata["is_manual"])
    if "ahr999" in metadata and metadata["ahr999"] is not None:
        tx.ahr999 = float(metadata["ahr999"])
    if metadata.get("notes"):
        tx.notes = metadata["notes"]
    if metadata.get("timestamp") is not None:
        tx.timestamp = metadata["timestamp"]
    if metadata.get("intended_amount_usd") not in (None, 0.0):
        tx.intended_amount_usd = float(metadata["intended_amount_usd"])
    return True


def _float_close(a: Optional[float], b: Optional[float], tol: float = 1e-12) -> bool:
    return abs(float(a or 0.0) - float(b or 0.0)) <= tol


def _final_order_row_differs_from_snapshot(tx: DCATransaction, snapshot: Dict[str, Any]) -> bool:
    """
    Compare final normalized row vs pre-reset persisted state for the same order.
    This is used for user-facing "did anything actually change?" reporting.
    """
    if int(snapshot.get("row_count") or 0) != 1:
        return True

    if (snapshot.get("source") or None) != (tx.source or None):
        return True
    if bool(snapshot.get("is_manual", False)) != bool(tx.is_manual):
        return True
    if not _float_close(snapshot.get("ahr999"), tx.ahr999):
        return True

    if not _float_close(snapshot.get("sum_quote_usd"), tx.executed_amount_usd or tx.fiat_amount):
        return True
    if not _float_close(snapshot.get("sum_btc"), tx.executed_amount_btc or tx.btc_amount):
        return True

    snap_fee_assets = snapshot.get("fee_assets") or set()
    if not isinstance(snap_fee_assets, set):
        snap_fee_assets = set(snap_fee_assets)
    if len(snap_fee_assets) <= 1:
        expected_asset = next(iter(snap_fee_assets)) if snap_fee_assets else ""
        if (tx.fee_asset or "") != expected_asset:
            return True
        if not _float_close(snapshot.get("sum_fee"), tx.fee_amount):
            return True
    else:
        if (tx.fee_asset or "") != "MIXED":
            return True

    return False


def _merge_split_orders_and_restore_metadata(
    session: Session,
    metadata_snapshot: Dict[int, Dict[str, Any]],
) -> Dict[str, int]:
    """
    Collapse split fills imported from Binance into one row per order_id, and restore
    semantic metadata from the pre-reset snapshot.
    """
    rows = session.exec(
        select(DCATransaction)
        .where(DCATransaction.binance_order_id.is_not(None))
        .order_by(col(DCATransaction.timestamp).asc(), col(DCATransaction.id).asc())
    ).all()
    if not rows:
        return {
            "merged_orders": 0,
            "removed_rows": 0,
            "metadata_restored": 0,
            "state_changed_orders": len(metadata_snapshot),
        }

    groups: Dict[int, List[DCATransaction]] = {}
    for tx in rows:
        if tx.binance_order_id is None:
            continue
        groups.setdefault(int(tx.binance_order_id), []).append(tx)

    merged_orders = 0
    removed_rows = 0
    metadata_restored = 0
    state_changed_orders = 0

    for order_id, group in groups.items():
        group = sorted(group, key=lambda t: (t.timestamp, t.id or 0))
        base = group[0]

        if len(group) > 1:
            merged_orders += 1
            removed_rows += len(group) - 1

            total_quote = 0.0
            total_btc = 0.0
            total_fee = 0.0
            fee_assets = set()
            trade_ids: List[int] = []
            earliest_ts = base.timestamp

            for tx in group:
                total_quote += float(tx.executed_amount_usd or tx.fiat_amount or 0.0)
                total_btc += float(tx.executed_amount_btc or tx.btc_amount or 0.0)
                fee_value = float(tx.fee_amount or 0.0)
                if fee_value:
                    total_fee += fee_value
                if tx.fee_asset:
                    fee_assets.add(tx.fee_asset)
                if tx.binance_trade_id is not None:
                    trade_ids.append(int(tx.binance_trade_id))
                if tx.timestamp < earliest_ts:
                    earliest_ts = tx.timestamp

            avg_price = (total_quote / total_btc) if total_btc > 0 else float(base.price or 0.0)

            base.timestamp = earliest_ts
            base.status = "SUCCESS"
            base.fiat_amount = total_quote
            base.btc_amount = total_btc
            base.price = avg_price
            base.executed_amount_usd = total_quote
            base.executed_amount_btc = total_btc
            base.avg_execution_price_usd = avg_price
            base.binance_trade_id = min(trade_ids) if trade_ids else base.binance_trade_id

            if len(fee_assets) <= 1:
                base.fee_amount = total_fee
                if fee_assets:
                    base.fee_asset = next(iter(fee_assets))
            else:
                # Different fee assets cannot be safely summed into one scalar.
                logger.warning(
                    f"Mixed fee assets for order {order_id} during reset/sync merge: {sorted(fee_assets)}"
                )
                base.fee_amount = None
                base.fee_asset = "MIXED"

            for extra in group[1:]:
                session.delete(extra)

        if _apply_preserved_order_metadata(base, metadata_snapshot.get(order_id)):
            metadata_restored += 1
        if _final_order_row_differs_from_snapshot(base, metadata_snapshot.get(order_id) or {}):
            state_changed_orders += 1
        session.add(base)

    missing_order_ids = set(metadata_snapshot.keys()) - set(groups.keys())
    state_changed_orders += len(missing_order_ids)

    session.commit()
    return {
        "merged_orders": merged_orders,
        "removed_rows": removed_rows,
        "metadata_restored": metadata_restored,
        "state_changed_orders": state_changed_orders,
    }


def _try_collect_static_generation_status() -> Optional[dict]:
    """
    Best-effort status probe for current background process.
    Returns None if no process or probe fails.
    """
    global _static_generation_process
    if _static_generation_process is None:
        return None
    try:
        from dca_service.services.static_generator import check_static_generation_status
        return check_static_generation_status(_static_generation_process)
    except Exception as e:
        logger.warning(f"Failed to probe static generation process status, resetting state: {e}")
        _static_generation_process = None
        return None


def _read_log_tail(path: str | None, max_chars: int = 2000) -> str:
    if not path:
        return ""
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return content[-max_chars:]
    except Exception:
        return ""


def _get_binance_client(session: Session) -> Optional[BinanceClient]:
    """Get authenticated Binance client (READ_ONLY preferred)"""
    # Try READ_ONLY first
    creds = session.query(BinanceCredentials).filter(
        BinanceCredentials.credential_type == "READ_ONLY"
    ).first()
    
    # Fallback to TRADING
    if not creds:
        creds = session.query(BinanceCredentials).filter(
            BinanceCredentials.credential_type == "TRADING"
        ).first()
    
    if not creds:
        return None
    
    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
        return BinanceClient(api_key, api_secret)
    except Exception:
        return None


@router.get("/transactions", response_model=List[UnifiedTransaction])
async def read_transactions(
    offset: int = 0,
    limit: int = Query(default=1000, le=5000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    """
    Fetch list of all transactions from LOCAL DATABASE only.
    Includes both DCA transactions and synced manual trades.
    """
    # Fetch all transactions from database (DCA + Manual)
    # Sort by timestamp descending
    statement = select(DCATransaction).order_by(col(DCATransaction.timestamp).desc()).offset(offset).limit(limit)
    transactions = session.exec(statement).all()
    
    unified_list = []
    
    for tx in transactions:
        badge, tx_type = _transaction_display_source_and_type(tx)
            
        # Ensure timestamp is timezone-aware
        tx_timestamp = tx.timestamp
        if tx_timestamp.tzinfo is None:
            tx_timestamp = tx_timestamp.replace(tzinfo=timezone.utc)
            
        unified_list.append(UnifiedTransaction(
            id=tx.binance_order_id or tx.id,  # Use Binance Order ID if available, else DB ID
            timestamp=tx_timestamp,
            type=tx_type,
            status=tx.status,
            btc_amount=tx.executed_amount_btc or tx.btc_amount or 0.0,
            fiat_amount=tx.executed_amount_usd or tx.fiat_amount or 0.0,
            price=tx.avg_execution_price_usd or tx.price or 0.0,
            notes=tx.notes,
            source=badge,
            ahr999=tx.ahr999,
            fee_amount=tx.fee_amount or 0.0,
            fee_asset=tx.fee_asset or "USDC"
        ))
    
    return unified_list


@router.post("/transactions/sync")
async def sync_transactions(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    """
    Trigger manual synchronization of trades from Binance.
    Fetches only new trades since the last sync.
    """
    from dca_service.services.sync_service import TradeSyncService
    
    service = TradeSyncService(session)
    count = await service.sync_trades()
    
    return {"success": True, "new_trades_count": count}


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def read_transaction(
    transaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    transaction = session.get(DCATransaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction



@router.post("/transactions/clear-simulated")
async def clear_simulated_transactions(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    """
    Reset transaction history and re-sync from Binance.
    Deletes ALL local transactions and fetches fresh data from Binance.
    
    Returns:
        dict: Success status and sync result
    """
    # Snapshot non-reconstructable metadata (ahr999/source/is_manual/notes) for
    # Binance-backed orders before reset so we can restore semantics after re-sync.
    metadata_snapshot = _build_order_metadata_snapshot(session)

    # Delete ALL transactions
    # Note: We use delete() with where(True) or just delete(DCATransaction) depending on SQLModel version
    # But session.exec(delete(DCATransaction)) is the standard way
    statement = delete(DCATransaction)
    session.exec(statement)
    session.commit()
    
    # Trigger sync from scratch
    from dca_service.services.sync_service import TradeSyncService
    
    service = TradeSyncService(session)
    count = await service.sync_trades(start_from_scratch=True)
    merge_stats = _merge_split_orders_and_restore_metadata(session, metadata_snapshot)
    
    return {
        "success": True,
        "deleted_count": "ALL",
        "synced_count": count,
        "merged_orders": merge_stats["merged_orders"],
        "merged_rows_removed": merge_stats["removed_rows"],
        "metadata_restored": merge_stats["metadata_restored"],
        "state_changed_orders": merge_stats["state_changed_orders"],
        "message": (
            f"History reset. Synced {count} trades from Binance. "
            f"Merged {merge_stats['merged_orders']} split orders."
        )
    }


@router.post("/email/test")
def test_email(current_user: User = Depends(get_current_user)):  # Authentication required
    """
    Test email configuration by sending a test message.
    Checks database settings first, then environment variables.
    
    Returns:
        dict: {"success": true} on success, {"success": false, "error": "..."} on failure
    """
    from dca_service.services.mailer import send_email, _get_email_config
    from dca_service.config import settings
    
    # Check if email is configured (DB or env)
    config = _get_email_config()
    
    if not config:
        return {
            "success": False,
            "error": "Email is not configured. Please fill in SMTP settings and enable email notifications."
        }
    
    try:
        # Send test email
        subject = f"{settings.PROJECT_NAME} Email Test"
        body = f"""If you received this, email configuration works!

Configuration Details:
- SMTP Host: {config['smtp_host']}
- SMTP Port: {config['smtp_port']}
- From: {config['email_from']}
- To: {config['email_to']}
- Source: {config['source']}

This is a test message from {settings.PROJECT_NAME}."""
        
        send_email(subject, body)
        
        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/static/regenerate")
async def regenerate_static_files(
    current_user: User = Depends(get_current_admin_user)
):
    """
    Manually trigger regeneration of static files (charts, data, etc.).
    
    Runs main.py as a background process to update all analysis files.
    This is the same process that runs automatically after DCA transactions.
    
    Returns:
        dict: {"success": true, "message": "...", "background": true} on success
    """
    global _static_generation_process, _static_generation_last_result
    global _static_generation_log_path
    try:
        from dca_service.services.static_generator import (
            get_static_generation_log_path,
            trigger_static_generation,
        )

        if _static_generation_process is not None:
            status = _try_collect_static_generation_status()
            if status and status.get("running"):
                return {
                    "success": True,
                    "message": "Static generation is already running.",
                    "background": True,
                    "pid": _static_generation_process.pid,
                    "running": True,
                    "log_path": _static_generation_log_path,
                }
            if status:
                _static_generation_last_result = status
                _static_generation_process = None

        _static_generation_log_path = str(get_static_generation_log_path())
        process = trigger_static_generation(background=True)
        _static_generation_process = process
        _static_generation_last_result = None

        return {
            "success": True,
            "message": "Static file generation started in background. This may take 30-120 seconds.",
            "background": True,
            "pid": process.pid if process else None,
            "running": True,
            "log_path": _static_generation_log_path,
        }
    except FileNotFoundError as e:
        logger.error(f"Failed to trigger static generation: {e}")
        return {
            "success": False,
            "error": "main.py not found. Check server configuration."
        }
    except Exception as e:
        logger.error(f"Error triggering static generation: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/static/regenerate/status")
async def regenerate_static_files_status(
    current_user: User = Depends(get_current_admin_user)
):
    """
    Check current static regeneration task status.

    Returns running/completed/failed state with brief output.
    """
    global _static_generation_process, _static_generation_last_result
    global _static_generation_log_path

    if _static_generation_process is not None:
        status = _try_collect_static_generation_status()
        if status and status.get("running"):
            return {
                "success": True,
                "running": True,
                "completed": False,
                "exit_code": None,
                "message": "Static generation is running.",
                "log_path": _static_generation_log_path,
                "log_tail": _read_log_tail(_static_generation_log_path, 2000),
            }

        if status:
            _static_generation_last_result = status
            _static_generation_process = None

    if _static_generation_last_result is None:
        return {
            "success": True,
            "running": False,
            "completed": False,
            "exit_code": None,
            "message": "No static generation task has run yet in this server process.",
            "log_path": _static_generation_log_path,
            "log_tail": _read_log_tail(_static_generation_log_path, 2000),
        }

    exit_code = _static_generation_last_result.get("exit_code")
    stderr = (_static_generation_last_result.get("stderr") or "").strip()
    stdout = (_static_generation_last_result.get("stdout") or "").strip()
    failed = exit_code not in (0, None)
    output_freshness = None
    message = "Static generation completed successfully." if not failed else "Static generation failed."
    if not failed:
        try:
            from dca_service.services.static_generator import (
                inspect_static_output_freshness,
                resolve_project_root,
            )

            output_freshness = inspect_static_output_freshness(resolve_project_root())
            if not output_freshness.get("fresh"):
                failed = True
                message = "Static generation completed but output data is stale."
        except Exception as e:
            logger.error(f"Failed to inspect static output freshness: {e}")
            failed = True
            message = "Static generation completed but output freshness could not be verified."

    return {
        "success": not failed,
        "running": False,
        "completed": True,
        "exit_code": exit_code,
        "message": message,
        "stderr_preview": stderr[-500:] if stderr else "",
        "stdout_preview": stdout[-500:] if stdout else "",
        "log_path": _static_generation_log_path,
        "log_tail": _read_log_tail(_static_generation_log_path, 4000),
        "output_freshness": output_freshness,
    }
