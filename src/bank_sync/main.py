"""Entrypoint for syncing Akahu transactions with Google Sheets."""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from bank_sync.akahu_client import AkahuClient, AkahuTransaction
from bank_sync.categoriser import Categoriser
from bank_sync.reconciliation import reconcile
from bank_sync.sheets_client import SheetsClient, TRANSACTION_HEADERS
from bank_sync.state_manager import SyncState
from bank_sync.ignore_rules import build_ignore_rules, should_ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)

# Get project root (2 levels up from this file: src/bank_sync/main.py -> root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_config(path: str | Path) -> Dict:
    with open(path, "r", encoding="utf-8") as config_file:
        return json.load(config_file)


def upload_categories(csv_path: str) -> None:
    """Upload category rules from a local CSV file to the CategoryMap sheet tab."""
    import csv
    
    config_env = os.environ.get("SYNC_CONFIG")
    config_path = Path(config_env) if config_env else PROJECT_ROOT / "config" / "config.json"
    config = load_config(config_path)
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or config.get("google_service_file")
    if not credentials_path:
        raise RuntimeError("Either GOOGLE_APPLICATION_CREDENTIALS environment variable or 'google_service_file' in config must be set")
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    # Read CSV file
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    if not rows:
        raise ValueError("CSV file is empty")
    
    LOGGER.info("Read %d rows from %s (including header)", len(rows), csv_path)
    
    sheets_client = SheetsClient(
        spreadsheet_id=config["spreadsheet_id"],
        credentials_path=credentials_path,
        transactions_tab=config.get("transactions_tab", "Transactions"),
        category_map_tab=config.get("category_map_tab", "CategoryMap"),
    )
    
    sheets_client.upload_category_rules(rows)
    LOGGER.info("Successfully uploaded %d category rules to CategoryMap sheet", len(rows) - 1)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned Google Sheets mutations without applying them",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Ignore saved sync state and fetch transactions from lookback_days window",
    )
    parser.add_argument(
        "--upload-categories",
        type=str,
        metavar="CSV_FILE",
        help="Upload category rules from a local CSV file to the CategoryMap sheet tab",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.upload_categories:
        upload_categories(args.upload_categories)
    else:
        run_sync(dry_run=args.dry_run, reset_state=args.reset_state)


def run_sync(dry_run: bool = False, reset_state: bool = False) -> None:
    config_env = os.environ.get("SYNC_CONFIG")
    config_path = Path(config_env) if config_env else PROJECT_ROOT / "config" / "config.json"
    config = load_config(config_path)
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or config.get("google_service_file")
    if not credentials_path:
        raise RuntimeError("Either GOOGLE_APPLICATION_CREDENTIALS environment variable or 'google_service_file' in config must be set")

    lookback_days = int(config.get("lookback_days", 7))
    end_timestamp = datetime.now(timezone.utc)

    state_path = Path(config.get("state_file", PROJECT_ROOT / "data" / "sync_state.json"))
    state = SyncState.load(state_path)
    if state.last_synced_at and not reset_state:
        start_timestamp = state.last_synced_at - timedelta(milliseconds=1)
    else:
        start_timestamp = end_timestamp - timedelta(days=lookback_days)
        if reset_state:
            LOGGER.info("Resetting sync state, will fetch from %s", start_timestamp)

    sheets_client = SheetsClient(
        spreadsheet_id=config["spreadsheet_id"],
        credentials_path=credentials_path,
        transactions_tab=config.get("transactions_tab", "Transactions"),
        category_map_tab=config.get("category_map_tab", "CategoryMap"),
    )

    existing = sheets_client.fetch_transactions()
    existing_map = {txn.id: txn for txn in existing if txn.id}

    category_rules = sheets_client.fetch_category_rules()
    categoriser = Categoriser(category_rules)
    ignore_rules = build_ignore_rules(config.get("ignore_rules"))

    akahu_client = AkahuClient(
        user_token=config["akahu_user_token"],
        app_token=config["akahu_app_token"],
    )

    LOGGER.info("Fetching Akahu transactions between %s and %s", start_timestamp, end_timestamp)
    fetched_transactions: List[AkahuTransaction] = list(
        akahu_client.fetch_settled_transactions(start_datetime=start_timestamp, end_datetime=end_timestamp)
    )
    LOGGER.info("Fetched %d transactions from Akahu", len(fetched_transactions))

    imported_at = datetime.now(timezone.utc)
    new_rows: List[List[str]] = []
    updates: List[tuple[int, List[str]]] = []
    seen_ids = set()

    # Process fetched transactions from Akahu
    for transaction in fetched_transactions:
        if should_ignore(transaction, ignore_rules):
            LOGGER.info("Ignoring transaction %s (%s) due to ignore rules", transaction.id, transaction.description_raw)
            continue
        seen_ids.add(transaction.id)
        transaction_dict = {
            "id": transaction.id,
            "date": transaction.date,
            "account": transaction.account,
            "amount": f"{transaction.amount:.2f}",
            "balance": "" if transaction.balance is None else f"{transaction.balance:.2f}",
            "description_raw": transaction.description_raw,
            "merchant_normalised": transaction.merchant_normalised,
            "source": transaction.source,
        }
        category, category_type = categoriser.categorise(transaction_dict)
        is_transfer = categoriser.detect_transfer(transaction_dict)
        row = transaction.to_row(category=category, category_type=category_type, is_transfer=is_transfer, imported_at=imported_at)

        if transaction.id not in existing_map:
            new_rows.append(row)
            continue

        sheet_txn = existing_map[transaction.id]
        if _needs_update(sheet_txn.data, row):
            updates.append((sheet_txn.row_index, row))

    # Recategorize all existing transactions that weren't fetched from Akahu
    # This ensures category/category_type updates are applied to all historical transactions
    for sheet_txn in existing:
        if sheet_txn.id in seen_ids or not sheet_txn.id:
            continue  # Already processed or no ID
        
        # Mark as seen so it doesn't get deleted
        seen_ids.add(sheet_txn.id)
        
        # Recategorize this existing transaction
        transaction_dict = {
            "id": sheet_txn.data.get("id", ""),
            "date": sheet_txn.data.get("date", ""),
            "account": sheet_txn.data.get("account", ""),
            "amount": sheet_txn.data.get("amount", ""),
            "balance": sheet_txn.data.get("balance", ""),
            "description_raw": sheet_txn.data.get("description_raw", ""),
            "merchant_normalised": sheet_txn.data.get("merchant_normalised", ""),
            "source": sheet_txn.data.get("source", ""),
        }
        category, category_type = categoriser.categorise(transaction_dict)
        is_transfer = categoriser.detect_transfer(transaction_dict)
        
        # Build the row with updated category/category_type
        row = [
            transaction_dict["id"],
            transaction_dict["date"],
            transaction_dict["account"],
            transaction_dict["amount"],
            transaction_dict["balance"],
            transaction_dict["description_raw"],
            transaction_dict["merchant_normalised"],
            category,
            category_type,
            str(is_transfer).upper(),
            transaction_dict["source"],
            sheet_txn.data.get("imported_at", ""),  # Keep original import time
        ]
        
        if _needs_update(sheet_txn.data, row):
            updates.append((sheet_txn.row_index, row))

    rows_to_delete = [txn.row_index for txn in existing if txn.id and txn.id not in seen_ids]

    LOGGER.info("Processing complete: %d new, %d updates, %d deletions", len(new_rows), len(updates), len(rows_to_delete))

    # Safety check: warn if deleting many transactions with few/no new ones
    deletion_threshold = int(config.get("deletion_warning_threshold", 50))
    if len(rows_to_delete) >= deletion_threshold and len(fetched_transactions) == 0:
        LOGGER.error(
            "SAFETY CHECK FAILED: About to delete %d transactions but fetched 0 new ones. "
            "This likely indicates a bug. Aborting to prevent data loss. "
            "Time window was: %s to %s",
            len(rows_to_delete),
            start_timestamp,
            end_timestamp
        )
        LOGGER.error("If this is intentional, increase deletion_warning_threshold in config.json")
        return

    if dry_run:
        for line in _format_mutation_summary(new_rows, updates, rows_to_delete):
            LOGGER.info("Dry-run: %s", line)
    else:
        if new_rows:
            sheets_client.append_transactions(new_rows)
        if updates:
            sheets_client.batch_update_transactions(updates)
        if rows_to_delete:
            sheets_client.delete_rows(rows_to_delete)

        # Update Dashboard with sync metadata
        if config.get("update_dashboard", True):
            dashboard_tab = config.get("dashboard_tab", "Dashboard")
            # Find the most recent transaction date from all existing transactions
            all_transactions = sheets_client.fetch_transactions()
            most_recent_date = ""
            if all_transactions:
                # Sort by date and get the most recent
                dates = [txn.data.get("date", "") for txn in all_transactions if txn.data.get("date")]
                if dates:
                    most_recent_date = max(dates)
            
            sheets_client.update_dashboard(
                last_sync_time=imported_at.isoformat(),
                most_recent_transaction_date=most_recent_date,
                dashboard_tab=dashboard_tab
            )

        # Re-fetch transactions after updates for accurate reconciliation
        if config.get("perform_reconciliation", False):
            updated_transactions = sheets_client.fetch_transactions()
            results = reconcile([txn.data for txn in updated_transactions])
            for result in results:
                if result.is_ok:
                    LOGGER.info("Reconciled %s: %.2f", result.account, result.expected_balance)
                else:
                    LOGGER.warning(
                        "Reconciliation drift for %s: expected %.2f vs sheet %.2f (diff %.2f)",
                        result.account,
                        result.expected_balance,
                        result.sheet_balance,
                        result.difference,
                    )

    if not dry_run:
        # Update sync state to current time so next run fetches only newer transactions
        state.last_synced_at = end_timestamp
        state.save(state_path)


def _needs_update(existing: Dict[str, str], new_row: List[str]) -> bool:
    for header, value in zip(TRANSACTION_HEADERS, new_row):
        if str(existing.get(header, "")) != value:
            return True
    return False


def _format_mutation_summary(
    new_rows: Sequence[Sequence[str]],
    updates: Sequence[tuple[int, Sequence[str]]],
    rows_to_delete: Iterable[int],
) -> List[str]:
    """Return human-friendly descriptions of planned sheet changes."""

    rows_to_delete_list = list(rows_to_delete)
    delete_count = len(rows_to_delete_list)
    summary: List[str] = []
    if new_rows:
        summary.append(f"append {len(new_rows)} new row(s)")
    if updates:
        summary.append(f"update {len(updates)} existing row(s)")
    if delete_count:
        summary.append(f"delete {delete_count} orphaned row(s)")
    if not summary:
        summary.append("no sheet mutations are required")
    return summary


if __name__ == "__main__":
    main()
