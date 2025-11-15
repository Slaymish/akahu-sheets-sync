"""Google Sheets helper utilities."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

LOGGER = logging.getLogger(__name__)

TRANSACTION_HEADERS = [
    "id",
    "date",
    "account",
    "amount",
    "balance",
    "description_raw",
    "merchant_normalised",
    "category",
    "is_transfer",
    "source",
    "imported_at",
]


@dataclass
class SheetTransaction:
    data: Dict[str, str]
    row_index: int

    @property
    def id(self) -> str:
        return self.data.get("id", "")


class SheetsClient:
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        credentials_path: str,
        transactions_tab: str = "Transactions",
        category_map_tab: str = "CategoryMap",
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._transactions_tab = transactions_tab
        self._category_tab = category_map_tab
        credentials = Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def fetch_transactions(self) -> List[SheetTransaction]:
        range_name = f"{self._transactions_tab}!A2:K"
        response = self._service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id, range=range_name
        ).execute()
        rows = response.get("values", [])
        transactions: List[SheetTransaction] = []
        for offset, row in enumerate(rows, start=2):
            padded = row + [""] * (len(TRANSACTION_HEADERS) - len(row))
            data = dict(zip(TRANSACTION_HEADERS, padded))
            transactions.append(SheetTransaction(data=data, row_index=offset))
        return transactions

    def append_transactions(self, rows: Iterable[List[str]]) -> None:
        if not rows:
            return
        range_name = f"{self._transactions_tab}!A:K"
        body = {"values": list(rows)}
        LOGGER.info("Appending %s new transactions", len(body["values"]))
        self._service.spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    def update_transaction(self, row_index: int, row: List[str]) -> None:
        range_name = f"{self._transactions_tab}!A{row_index}:K{row_index}"
        LOGGER.info("Updating row %s", row_index)
        self._service.spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()

    def delete_rows(self, row_indices: List[int]) -> None:
        if not row_indices:
            return
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": 0,
                        "dimension": "ROWS",
                        "startIndex": index - 1,
                        "endIndex": index,
                    }
                }
            }
            for index in sorted(row_indices, reverse=True)
        ]
        LOGGER.warning("Deleting %s transactions", len(row_indices))
        try:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id, body={"requests": requests}
            ).execute()
        except HttpError:
            LOGGER.exception("Failed deleting rows")
            raise

    def fetch_category_rules(self) -> List[Dict[str, str]]:
        range_name = f"{self._category_tab}!A2:D"
        response = self._service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id, range=range_name
        ).execute()
        rules = []
        for row in response.get("values", []):
            padded = row + [""] * (4 - len(row))
            rules.append(
                {
                    "pattern": padded[0],
                    "field": padded[1] or "merchant_normalised",
                    "category": padded[2] or "Uncategorised",
                    "priority": padded[3] or "1000",
                }
            )
        return rules
