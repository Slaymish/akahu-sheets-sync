#!/usr/bin/env python3
"""Test script to check what transactions Akahu API returns."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from bank_sync.akahu_client import AkahuClient


def main():
    # Load config
    config_path = Path(__file__).parent / "config" / "config.json"
    with open(config_path) as f:
        config = json.load(f)
    
    client = AkahuClient(
        user_token=config["akahu_user_token"],
        app_token=config["akahu_app_token"],
    )
    
    # Fetch transactions from the last 7 days
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=7)
    
    print(f"Fetching transactions from {start_time} to {end_time}\n")
    print("=" * 80)
    
    # Fetch with type=SETTLED filter
    print("\n🔹 SETTLED TRANSACTIONS (type=SETTLED):")
    print("-" * 80)
    
    settled_txns = list(client.fetch_settled_transactions(
        start_datetime=start_time,
        end_datetime=end_time
    ))
    
    if not settled_txns:
        print("No settled transactions found")
    else:
        # Sort by date descending (most recent first)
        settled_txns.sort(key=lambda t: t.date, reverse=True)
        
        print(f"\nFound {len(settled_txns)} settled transactions")
        print("\nMost recent 10 transactions:")
        print("-" * 80)
        
        for i, txn in enumerate(settled_txns[:10], 1):
            print(f"\n{i}. ID: {txn.id}")
            print(f"   Date: {txn.date}")
            print(f"   Account: {txn.account}")
            print(f"   Amount: ${txn.amount:.2f}")
            print(f"   Description: {txn.description_raw}")
            print(f"   Merchant: {txn.merchant_normalised}")
    
    # Now test WITHOUT the type filter to see ALL transactions (including pending)
    print("\n\n" + "=" * 80)
    print("🔹 ALL TRANSACTIONS (no type filter - includes PENDING):")
    print("-" * 80)
    
    # Make a direct request without type filter
    params = {
        "start": start_time.isoformat(),
        "end": end_time.isoformat(),
        "limit": 100,
    }
    
    all_txns_payload = client._request("GET", "/transactions", params=params)
    all_txns = all_txns_payload.get("items", [])
    
    print(f"\nFound {len(all_txns)} total transactions (settled + pending)")
    
    # Show the most recent ones with their type
    print("\nMost recent 10 transactions (with type):")
    print("-" * 80)
    
    # Sort by date
    all_txns.sort(key=lambda t: t.get("date", ""), reverse=True)
    
    for i, txn in enumerate(all_txns[:10], 1):
        txn_type = txn.get("type", "UNKNOWN")
        date_str = txn.get("date", "N/A")
        amount = txn.get("amount", 0)
        description = txn.get("description", "")
        
        print(f"\n{i}. Type: {txn_type}")
        print(f"   Date: {date_str}")
        print(f"   Amount: ${amount:.2f}")
        print(f"   Description: {description}")
    
    # Count by type
    type_counts = {}
    for txn in all_txns:
        txn_type = txn.get("type", "UNKNOWN")
        type_counts[txn_type] = type_counts.get(txn_type, 0) + 1
    
    print("\n" + "=" * 80)
    print("Summary by transaction type:")
    print("-" * 80)
    for txn_type, count in sorted(type_counts.items()):
        print(f"{txn_type}: {count}")


if __name__ == "__main__":
    main()
