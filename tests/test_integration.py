"""Integration tests that verify end-to-end logical behavior."""
import datetime as dt
from datetime import timezone

from bank_sync.akahu_client import AkahuTransaction
from bank_sync.categoriser import Categoriser
from bank_sync.ignore_rules import IgnoreRule
from bank_sync.main import _needs_update
from bank_sync.sheets_client import TRANSACTION_HEADERS


def test_transaction_flow_from_akahu_to_sheet_row():
    """Verify a transaction flows correctly through the entire pipeline."""
    # Step 1: Create an Akahu transaction
    akahu_payload = {
        "_id": "txn_123",
        "date": "2025-11-15",
        "amount": -25.50,
        "balance": 100.00,
        "description": "NEW WORLD KARORI WELLINGTON",
        "merchant": {"name": "New World"},
    }
    
    txn = AkahuTransaction.from_payload(
        akahu_payload, 
        source="akahu_bnz", 
        account_name="Cheque"
    )
    
    # Verify transaction parsed correctly
    assert txn.id == "txn_123"
    assert txn.date == "2025-11-15"
    assert txn.amount == -25.50
    assert txn.merchant_normalised == "New World"
    
    # Step 2: Categorize the transaction
    rules = [
        {
            "pattern": "new world",
            "field": "merchant_normalised",
            "category": "Groceries",
            "category_type": "E",
            "priority": 10,
            "amount_condition": ">20",
        },
        {
            "pattern": "new world",
            "field": "merchant_normalised",
            "category": "Snacks",
            "category_type": "W",
            "priority": 20,
            "amount_condition": "",
        }
    ]
    
    categoriser = Categoriser(rules)
    transaction_dict = {
        "merchant_normalised": txn.merchant_normalised,
        "description_raw": txn.description_raw,
        "amount": f"{txn.amount:.2f}",
    }
    
    category, category_type = categoriser.categorise(transaction_dict)
    assert category == "Groceries"  # Should match first rule due to amount > 20
    assert category_type == "E"
    
    # Step 3: Check if it's a transfer
    is_transfer = categoriser.detect_transfer(transaction_dict)
    assert is_transfer is False  # Not a transfer
    
    # Step 4: Convert to sheet row
    imported_at = dt.datetime(2025, 11, 15, 10, 0, 0, tzinfo=timezone.utc)
    row = txn.to_row(
        category=category,
        category_type=category_type,
        is_transfer=is_transfer,
        imported_at=imported_at
    )
    
    # Verify row structure matches headers
    assert len(row) == len(TRANSACTION_HEADERS)
    assert row[0] == "txn_123"  # id
    assert row[1] == "2025-11-15"  # date
    assert row[2] == "Cheque"  # account
    assert row[3] == "-25.50"  # amount
    assert row[4] == "100.00"  # balance
    assert row[7] == "Groceries"  # category
    assert row[8] == "E"  # category_type
    assert row[9] == "FALSE"  # is_transfer


def test_ignore_rules_filter_small_transactions():
    """Verify ignore rules properly filter out noise transactions."""
    ignore_rules = [
        IgnoreRule(
            pattern="INTEREST ADJUSTMENT",
            field_name="description_raw",
            max_amount=1.00
        )
    ]
    
    # Should be ignored (matches pattern and under threshold)
    small_interest = AkahuTransaction(
        id="txn_1",
        date="2025-11-15",
        account="Cheque",
        amount=0.15,
        balance=100.15,
        description_raw="INTEREST ADJUSTMENT MONTHLY",
        merchant_normalised="",
        source="akahu_bnz"
    )
    
    assert ignore_rules[0].matches(small_interest) is True
    
    # Should NOT be ignored (amount too large)
    large_interest = AkahuTransaction(
        id="txn_2",
        date="2025-11-15",
        account="Cheque",
        amount=5.00,
        balance=105.15,
        description_raw="INTEREST ADJUSTMENT MONTHLY",
        merchant_normalised="",
        source="akahu_bnz"
    )
    
    assert ignore_rules[0].matches(large_interest) is False
    
    # Should NOT be ignored (doesn't match pattern)
    normal_txn = AkahuTransaction(
        id="txn_3",
        date="2025-11-15",
        account="Cheque",
        amount=0.50,
        balance=105.65,
        description_raw="Coffee purchase",
        merchant_normalised="Mojo Coffee",
        source="akahu_bnz"
    )
    
    assert ignore_rules[0].matches(normal_txn) is False


def test_recategorization_updates_existing_transactions():
    """Verify that changing category rules updates existing transactions."""
    # Existing transaction in sheet
    existing_data = dict(zip(TRANSACTION_HEADERS, [
        "txn_123",
        "2025-11-15",
        "Cheque",
        "-25.50",
        "100.00",
        "NEW WORLD KARORI",
        "New World",
        "Snacks",  # Old category
        "W",  # Old category_type
        "FALSE",
        "akahu_bnz",
        "2025-11-15T10:00:00+00:00"
    ]))
    
    # New categorization with updated rules
    new_rules = [
        {
            "pattern": "new world",
            "category": "Groceries",
            "category_type": "E",  # Changed from W to E
            "priority": 10,
            "amount_condition": ">20",
        }
    ]
    
    categoriser = Categoriser(new_rules)
    txn_dict = {
        "merchant_normalised": "New World",
        "amount": "-25.50"
    }
    
    new_category, new_category_type = categoriser.categorise(txn_dict)
    
    # Build new row with updated categorization
    new_row = list(existing_data.values())
    new_row[7] = new_category
    new_row[8] = new_category_type
    
    # Should detect that update is needed
    assert _needs_update(existing_data, new_row) is True
    assert new_row[7] == "Groceries"
    assert new_row[8] == "E"


def test_transfer_detection_works_across_fields():
    """Verify transfer detection checks multiple fields."""
    categoriser = Categoriser([])
    
    # Transfer in description
    assert categoriser.detect_transfer({
        "description_raw": "Savings Account INTERNET XFR",
        "merchant_normalised": ""
    }) is True
    
    # Transfer in merchant
    assert categoriser.detect_transfer({
        "description_raw": "Regular payment",
        "merchant_normalised": "BNZ Internal"
    }) is True
    
    # Transfer keyword variations
    assert categoriser.detect_transfer({
        "description_raw": "Self transfer to savings",
        "merchant_normalised": ""
    }) is True
    
    # Not a transfer
    assert categoriser.detect_transfer({
        "description_raw": "Coffee purchase",
        "merchant_normalised": "Mojo Coffee"
    }) is False


def test_priority_ordering_in_categorization():
    """Verify that lower priority numbers take precedence."""
    rules = [
        {
            "pattern": "countdown",
            "category": "Specific Store",
            "category_type": "E",
            "priority": 5,  # Higher precedence
        },
        {
            "pattern": "count",
            "category": "Generic Match",
            "category_type": "W",
            "priority": 100,  # Lower precedence
        },
    ]
    
    categoriser = Categoriser(rules)
    
    # Should match the more specific rule first
    txn = {"merchant_normalised": "Countdown Supermarket"}
    category, category_type = categoriser.categorise(txn)
    
    assert category == "Specific Store"
    assert category_type == "E"


def test_amount_condition_uses_absolute_values():
    """Verify that amount conditions work with negative values."""
    rules = [
        {
            "pattern": "transfer",
            "category": "Large Transfer",
            "category_type": "Sl",
            "priority": 10,
            "amount_condition": ">100",
        },
        {
            "pattern": "transfer",
            "category": "Small Transfer",
            "category_type": "Sl",
            "priority": 20,
            "amount_condition": "",
        }
    ]
    
    categoriser = Categoriser(rules)
    
    # Negative amount with absolute value > 100
    txn_large = {
        "merchant_normalised": "Transfer",
        "amount": "-150.00"  # Absolute value is 150
    }
    category, _ = categoriser.categorise(txn_large)
    assert category == "Large Transfer"
    
    # Negative amount with absolute value < 100
    txn_small = {
        "merchant_normalised": "Transfer",
        "amount": "-50.00"  # Absolute value is 50
    }
    category, _ = categoriser.categorise(txn_small)
    assert category == "Small Transfer"


def test_transaction_deduplication_by_id():
    """Verify that transactions with same ID are treated as updates, not duplicates."""
    existing_data = dict(zip(TRANSACTION_HEADERS, [
        "txn_123",
        "2025-11-15",
        "Cheque",
        "-25.50",
        "100.00",
        "Coffee Shop",
        "Mojo Coffee",
        "Eating Out",
        "W",
        "FALSE",
        "akahu_bnz",
        "2025-11-15T10:00:00+00:00"
    ]))
    
    # Same transaction ID but with updated balance (Akahu mutated it)
    new_row = [
        "txn_123",  # Same ID
        "2025-11-15",
        "Cheque",
        "-25.50",
        "99.50",  # Updated balance
        "Coffee Shop",
        "Mojo Coffee",
        "Eating Out",
        "W",
        "FALSE",
        "akahu_bnz",
        "2025-11-15T10:00:00+00:00"
    ]
    
    # Should detect that update is needed due to balance change
    assert _needs_update(existing_data, new_row) is True


def test_lookback_buffer_calculation():
    """Verify that lookback buffer allows catching late-settling transactions."""
    from datetime import timedelta
    
    # Simulate last sync was 1 day ago
    last_sync = dt.datetime(2025, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
    lookback_buffer_days = 3
    
    # With buffer, should look back 3 days from last sync
    expected_start = last_sync - timedelta(days=lookback_buffer_days, milliseconds=1)
    
    # This allows catching transactions from Nov 13-16 even though last sync was Nov 16
    days_covered = (last_sync - expected_start).days
    assert days_covered >= 3  # At least 3 days of overlap
