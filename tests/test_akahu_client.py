import datetime as dt
from typing import Dict, List

import pytest

from akahu_client import AkahuClient, AkahuTransaction, _ensure_iso_date, _safe_float


class FakeResponse:
    def __init__(self, payload: Dict):
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - nothing to do
        return None

    def json(self) -> Dict:
        return self._payload


class FakeSession:
    def __init__(self, responses: List[Dict]):
        self._responses = responses
        self.request_calls = []

    def request(self, method, url, headers=None, params=None, timeout=None):
        self.request_calls.append((method, url, headers, params, timeout))
        if not self._responses:
            raise AssertionError("No more fake responses configured")
        return FakeResponse(self._responses.pop(0))


@pytest.fixture
def transaction_payload():
    return {
        "_id": "txn_123",
        "date": "2023-09-02",
        "account": {"name": "Cheque"},
        "amount": "-12.34",
        "balance": "120.55",
        "description": "Countdown",
        "merchant": {"name": "Countdown"},
    }


def test_transaction_from_payload(transaction_payload):
    txn = AkahuTransaction.from_payload(transaction_payload, source="akahu_bnz", account_name="Cheque")
    assert txn.id == "txn_123"
    assert txn.account == "Cheque"
    assert txn.amount == pytest.approx(-12.34)
    assert txn.balance == pytest.approx(120.55)
    assert txn.merchant_normalised == "Countdown"
    assert txn.source == "akahu_bnz"


def test_transaction_to_row_formats_numbers(transaction_payload):
    txn = AkahuTransaction.from_payload(transaction_payload, source="akahu_bnz", account_name="Cheque")
    row = txn.to_row(category="Groceries", is_transfer=False, imported_at=dt.datetime(2023, 9, 2, 10, 0))
    assert row[:4] == ["txn_123", "2023-09-02", "Cheque", "-12.34"]
    assert row[4] == "120.55"
    assert row[7] == "Groceries"
    assert row[8] == "FALSE"


def test_fetch_settled_transactions_paginates(transaction_payload):
    # Mock /accounts response first, then transaction pages
    responses = [
        {
            "items": [
                {"_id": "acc_1", "name": "Cheque"},
            ],
        },
        {
            "items": [
                {**transaction_payload, "_account": "acc_1"},
            ],
            "cursor": {"next": "next-token"},
        },
        {
            "items": [
                {**transaction_payload, "_id": "txn_456", "_account": "acc_1"},
            ],
            "cursor": {},
        },
    ]
    session = FakeSession(responses)
    client = AkahuClient(user_token="user", app_token="app", session=session)

    start = dt.datetime(2023, 9, 1, 0, 0)
    end = dt.datetime(2023, 9, 3, 0, 0)

    fetched = list(client.fetch_settled_transactions(start_datetime=start, end_datetime=end))

    assert [txn.id for txn in fetched] == ["txn_123", "txn_456"]
    assert len(session.request_calls) == 3  # 1 for /accounts, 2 for transactions
    for _, _, headers, _, _ in session.request_calls:
        assert headers["Authorization"].startswith("Bearer ")
        assert headers["X-Akahu-Id"] == "app"


def test_safe_float_handles_invalid_values():
    assert _safe_float("12.3") == pytest.approx(12.3)
    assert _safe_float(None) is None
    assert _safe_float("not-a-number") is None


def test_ensure_iso_date_handles_formats():
    assert _ensure_iso_date("2023-01-05") == "2023-01-05"
    assert _ensure_iso_date("2023-01-05T12:00:00Z").startswith("2023-01-05")
    today = dt.date.today().isoformat()
    assert _ensure_iso_date(None) == today
