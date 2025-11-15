from akahu_client import AkahuTransaction
from ignore_rules import build_ignore_rules, should_ignore


def _txn(**overrides):
    defaults = {
        "id": "1",
        "date": "2024-01-01",
        "account": "Main",
        "amount": 0.5,
        "balance": 10.0,
        "description_raw": "interest adjustment",
        "merchant_normalised": "bnz",
        "source": "akahu_bnz",
    }
    defaults.update(overrides)
    return AkahuTransaction(**defaults)


def test_build_ignore_rules_skips_invalid_entries():
    rules = build_ignore_rules([{}, {"field": "description_raw", "pattern": "fee"}])
    assert len(rules) == 1
    assert rules[0].field_name == "description_raw"


def test_ignore_rule_matches_pattern_and_amount_bounds():
    rules = build_ignore_rules(
        [
            {
                "pattern": "interest",
                "field": "description_raw",
                "max_amount": 1,
            }
        ]
    )
    assert should_ignore(_txn(amount=0.75), rules) is True
    assert should_ignore(_txn(amount=5.0), rules) is False


def test_ignore_rule_defaults_field_and_is_case_insensitive():
    rules = build_ignore_rules([
        {
            "pattern": "ADJUSTMENT",
        }
    ])
    assert should_ignore(_txn(description_raw="Tiny adjustment"), rules) is True
    assert should_ignore(_txn(description_raw="Major payment"), rules) is False
