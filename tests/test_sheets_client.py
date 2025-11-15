from typing import Any, Dict, List

import pytest

import sheets_client as sc


class FakeRequest:
    def __init__(self, response: Dict[str, Any] | None = None, callback=None):
        self._response = response or {}
        self._callback = callback

    def execute(self):
        if self._callback:
            self._callback()
        return self._response


class FakeValuesResource:
    def __init__(self, service: "FakeSheetsService"):
        self._service = service

    def get(self, spreadsheetId: str, range: str):
        self._service.calls.append(("get", range))
        if not self._service.get_responses:
            raise AssertionError("No fake response configured")
        return FakeRequest(self._service.get_responses.pop(0))

    def append(self, spreadsheetId: str, range: str, valueInputOption: str, body: Dict):
        def record():
            self._service.append_calls.append((range, valueInputOption, body))

        return FakeRequest(callback=record)

    def update(self, spreadsheetId: str, range: str, valueInputOption: str, body: Dict):
        def record():
            self._service.update_calls.append((range, valueInputOption, body))

        return FakeRequest(callback=record)


class FakeSpreadsheetsResource:
    def __init__(self, service: "FakeSheetsService"):
        self._service = service
        self._values = FakeValuesResource(service)

    def values(self):
        return self._values

    def batchUpdate(self, spreadsheetId: str, body: Dict):
        def record():
            self._service.batch_update_calls.append(body)

        return FakeRequest(callback=record)


class FakeSheetsService:
    def __init__(self, get_responses: List[Dict[str, Any]] | None = None):
        self.calls: List = []
        self.append_calls: List = []
        self.update_calls: List = []
        self.batch_update_calls: List = []
        self.get_responses = list(get_responses or [])
        self._spreadsheets = FakeSpreadsheetsResource(self)

    def spreadsheets(self):
        return self._spreadsheets


@pytest.fixture(autouse=True)
def patch_build(monkeypatch):
    service = FakeSheetsService()

    def fake_build(*args, **kwargs):
        return service

    monkeypatch.setattr(sc, "build", fake_build)
    return service


def test_fetch_transactions_pads_rows(patch_build):
    patch_build.get_responses = [
        {"values": [["id1", "2023-09-01", "Cheque", "12.00"], ["id2"]]},
    ]
    client = sc.SheetsClient(spreadsheet_id="sheet", credentials_path="creds.json")
    txns = client.fetch_transactions()
    assert txns[0].data["amount"] == "12.00"
    assert txns[1].data["merchant_normalised"] == ""


def test_fetch_category_rules_applies_defaults(patch_build):
    patch_build.get_responses = [
        {"values": [["pattern", "", "", "", ""], ["", "desc", "Cat", "5", "<=10"]]},
    ]
    client = sc.SheetsClient(spreadsheet_id="sheet", credentials_path="creds.json")
    rules = client.fetch_category_rules()
    assert rules[0]["field"] == "merchant_normalised"
    assert rules[0]["category"] == "Uncategorised"
    assert rules[1]["priority"] == "5"
    assert rules[1]["amount_condition"] == "<=10"


def test_append_transactions_noop_on_empty(patch_build):
    client = sc.SheetsClient(spreadsheet_id="sheet", credentials_path="creds.json")
    client.append_transactions([])
    assert patch_build.append_calls == []


def test_append_update_and_delete(patch_build):
    client = sc.SheetsClient(spreadsheet_id="sheet", credentials_path="creds.json")
    row = ["a"] * len(sc.TRANSACTION_HEADERS)
    client.append_transactions([row])
    client.update_transaction(5, row)
    client.delete_rows([5, 3])

    assert patch_build.append_calls[0][0] == "Transactions!A:K"
    assert patch_build.update_calls[0][0] == "Transactions!A5:K5"
    assert patch_build.batch_update_calls
    delete_body = patch_build.batch_update_calls[0]["requests"]
    indices = [req["deleteDimension"]["range"]["startIndex"] for req in delete_body]
    assert indices == [4, 2]
