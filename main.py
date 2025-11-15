"""Entrypoint for syncing Akahu transactions with Google Sheets."""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from akahu_client import AkahuClient, AkahuTransaction
from categoriser import Categoriser
from reconciliation import reconcile
from sheets_client import SheetsClient, TRANSACTION_HEADERS
from state_manager import SyncState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def load_config(path: str | Path) -> Dict:
    with open(path, "r", encoding="utf-8") as config_file:
        return json.load(config_file)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned Google Sheets mutations without applying them",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    run_sync(dry_run=args.dry_run)


def run_sync(dry_run: bool = False) -> None:
    config_path = Path(os.environ.get("SYNC_CONFIG", "config.json"))
    config = load_config(config_path)
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS environment variable must be set")

    lookback_days = int(config.get("lookback_days", 7))
    end_timestamp = datetime.now(timezone.utc)

    state_path = Path(config.get("state_file", "sync_state.json"))
    state = SyncState.load(state_path)
    if state.last_synced_at:
        start_timestamp = state.last_synced_at - timedelta(milliseconds=1)
    else:
        start_timestamp = end_timestamp - timedelta(days=lookback_days)

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

    akahu_client = AkahuClient(
        user_token=config["akahu_user_token"],
        app_token=config["akahu_app_token"],
    )

    LOGGER.info("Fetching Akahu transactions between %s and %s", start_timestamp, end_timestamp)
    fetched_transactions: List[AkahuTransaction] = list(
        akahu_client.fetch_settled_transactions(start_datetime=start_timestamp, end_datetime=end_timestamp)
    )

    imported_at = datetime.now(timezone.utc)
    new_rows: List[List[str]] = []
    updates: List[tuple[int, List[str]]] = []
    seen_ids = set()

    for transaction in fetched_transactions:
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
        category = categoriser.categorise(transaction_dict)
        is_transfer = categoriser.detect_transfer(transaction_dict)
        row = transaction.to_row(category=category, is_transfer=is_transfer, imported_at=imported_at)

        if transaction.id not in existing_map:
            new_rows.append(row)
            continue

        sheet_txn = existing_map[transaction.id]
        if _needs_update(sheet_txn.data, row):
            updates.append((sheet_txn.row_index, row))

    rows_to_delete = [txn.row_index for txn in existing if txn.id and txn.id not in seen_ids]

    if dry_run:
        for line in _format_mutation_summary(new_rows, updates, rows_to_delete):
            LOGGER.info("Dry-run: %s", line)
    else:
        if new_rows:
            sheets_client.append_transactions(new_rows)
        if updates:
            for row_index, row in updates:
                sheets_client.update_transaction(row_index, row)
        if rows_to_delete:
            sheets_client.delete_rows(rows_to_delete)

    if config.get("perform_reconciliation", False):
        results = reconcile([txn.data for txn in existing])
        for result in results:
            if result.is_ok:
                LOGGER.info("Reconciled %s", result.account)
            else:
                LOGGER.warning(
                    "Reconciliation drift for %s: expected %.2f vs sheet %.2f (diff %.2f)",
                    result.account,
                    result.expected_balance,
                    result.sheet_balance,
                    result.difference,
                )

    if not dry_run:
        state.last_synced_at = max(state.last_synced_at or start_timestamp, end_timestamp)
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
