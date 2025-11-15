from categoriser import Categoriser


def test_categoriser_applies_highest_priority_match():
    rules = [
        {"pattern": "countdown", "category": "Groceries", "priority": 50},
        {"pattern": "count", "category": "Misc", "priority": 100},
    ]
    categoriser = Categoriser(rules)
    txn = {"merchant_normalised": "Countdown Ponsonby"}
    assert categoriser.categorise(txn) == "Groceries"


def test_categoriser_skips_empty_patterns():
    rules = [
        {"pattern": "", "category": "Ignored"},
        {"pattern": "ferry", "category": "Transport"},
    ]
    categoriser = Categoriser(rules)
    assert categoriser.categorise({"merchant_normalised": "Ferry ride"}) == "Transport"


def test_categoriser_honours_amount_conditions():
    rules = [
        {
            "pattern": "new world",
            "category": "Groceries",
            "amount_condition": "> 10",
            "priority": 5,
        },
        {
            "pattern": "new world",
            "category": "Snacks",
            "amount_condition": "< 10",
            "priority": 10,
        },
    ]
    categoriser = Categoriser(rules)
    assert (
        categoriser.categorise({"merchant_normalised": "New World", "amount": "12.00"})
        == "Groceries"
    )
    assert (
        categoriser.categorise({"merchant_normalised": "New World", "amount": "5.00"})
        == "Snacks"
    )


def test_categoriser_supports_exact_amounts_and_or_conditions():
    rules = [
        {
            "pattern": "coffee",
            "category": "Work Coffee",
            "amount_condition": "4.5",
            "priority": 1,
        },
        {
            "pattern": "coffee",
            "category": "Free Coffee",
            "amount_condition": "0 or $-0",
            "priority": 5,
        },
        {
            "pattern": "coffee",
            "category": "Discount Coffee",
            "amount_condition": "$-2 OR -4",
            "priority": 10,
        },
    ]
    categoriser = Categoriser(rules)
    assert (
        categoriser.categorise({"merchant_normalised": "Coffee", "amount": "4.50"})
        == "Work Coffee"
    )
    assert (
        categoriser.categorise({"merchant_normalised": "Coffee", "amount": "0"})
        == "Free Coffee"
    )
    assert (
        categoriser.categorise({"merchant_normalised": "Coffee", "amount": "-4"})
        == "Discount Coffee"
    )


def test_categoriser_ignores_amount_condition_when_unparseable():
    rules = [
        {
            "pattern": "countdown",
            "category": "Groceries",
            "amount_condition": "bigger than lots",
        }
    ]
    categoriser = Categoriser(rules)
    assert categoriser.categorise({"merchant_normalised": "Countdown", "amount": "1"}) == "Groceries"


def test_categoriser_falls_back_when_amount_missing():
    rules = [
        {
            "pattern": "fuel",
            "category": "Motoring",
            "amount_condition": ">= 20",
        },
        {"pattern": "fuel", "category": "Misc"},
    ]
    categoriser = Categoriser(rules)
    assert categoriser.categorise({"merchant_normalised": "Fuel stop"}) == "Misc"


def test_detect_transfer_checks_multiple_fields():
    txn = {"description_raw": "Internal Transfer", "merchant_normalised": "BNZ"}
    assert Categoriser.detect_transfer(txn) is True
    assert Categoriser.detect_transfer({"description_raw": "Cafe"}) is False
