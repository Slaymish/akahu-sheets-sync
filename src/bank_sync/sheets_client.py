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
    "category_type",
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
        self._sheet_id_cache: dict[str, int] = {}

    def _get_sheet_id(self, sheet_name: str) -> int:
        """Get the sheetId for a given sheet name."""
        if sheet_name in self._sheet_id_cache:
            return self._sheet_id_cache[sheet_name]
        
        metadata = self._service.spreadsheets().get(spreadsheetId=self._spreadsheet_id).execute()
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            title = properties.get("title", "")
            sheet_id = properties.get("sheetId", 0)
            self._sheet_id_cache[title] = sheet_id
        
        return self._sheet_id_cache.get(sheet_name, 0)

    def fetch_transactions(self) -> List[SheetTransaction]:
        range_name = f"{self._transactions_tab}!A2:L"
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
        range_name = f"{self._transactions_tab}!A:L"
        body = {"values": list(rows)}
        LOGGER.info("Appending %s new transactions", len(body["values"]))
        self._service.spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    def update_transaction(self, row_index: int, row: List[str]) -> None:
        range_name = f"{self._transactions_tab}!A{row_index}:L{row_index}"
        LOGGER.info("Updating row %s", row_index)
        self._service.spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()

    def batch_update_transactions(self, updates: List[tuple[int, List[str]]]) -> None:
        """Update multiple rows in a single batch request."""
        if not updates:
            return
        
        data = [
            {
                "range": f"{self._transactions_tab}!A{row_index}:L{row_index}",
                "values": [row]
            }
            for row_index, row in updates
        ]
        
        LOGGER.info("Batch updating %d rows", len(updates))
        self._service.spreadsheets().values().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": data
            }
        ).execute()

    def delete_rows(self, row_indices: List[int]) -> None:
        if not row_indices:
            return
        sheet_id = self._get_sheet_id(self._transactions_tab)
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
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
        range_name = f"{self._category_tab}!A2:F"
        response = self._service.spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id, range=range_name
        ).execute()
        rules = []
        for row in response.get("values", []):
            padded = row + [""] * (6 - len(row))
            rules.append(
                {
                    "pattern": padded[0],
                    "field": padded[1] or "merchant_normalised",
                    "category": padded[2] or "Uncategorised",
                    "priority": padded[3] or "1000",
                    "amount_condition": padded[4],
                    "category_type": padded[5],
                }
            )
        return rules

    def upload_category_rules(self, rows: List[List[str]]) -> None:
        """Clear the CategoryMap sheet and upload new rules from CSV rows."""
        if not rows:
            raise ValueError("No rows to upload")
        
        # Clear existing content (keep header row)
        range_name = f"{self._category_tab}!A2:F"
        self._service.spreadsheets().values().clear(
            spreadsheetId=self._spreadsheet_id,
            range=range_name
        ).execute()
        LOGGER.info("Cleared existing category rules")
        
        # Upload new data (including header if first row)
        range_name = f"{self._category_tab}!A1:F"
        body = {"values": rows}
        self._service.spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        LOGGER.info("Uploaded %d rows to CategoryMap", len(rows))

    def update_dashboard(self, *, last_sync_time: str, most_recent_transaction_date: str, dashboard_tab: str = "Dashboard") -> None:
        """Update the Dashboard tab with sync metadata.
        
        Formats timestamps for Google Sheets to recognize as date/time values.
        Converts UTC to New Zealand time (Pacific/Auckland timezone).
        """
        from datetime import datetime, timedelta
        
        # Parse and format the sync time (ISO format) to NZ time
        try:
            sync_dt = datetime.fromisoformat(last_sync_time.replace('Z', '+00:00'))
            # Convert UTC to NZ time (UTC+13 for NZDT, UTC+12 for NZST)
            # Using fixed offset of +13 for summer time
            nz_offset = timedelta(hours=13)
            nz_dt = sync_dt + nz_offset
            formatted_sync_time = nz_dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            formatted_sync_time = last_sync_time
        
        # Transaction date is just a date (YYYY-MM-DD), which Sheets already understands
        formatted_transaction_date = most_recent_transaction_date
        
        data = [
            {
                "range": f"{dashboard_tab}!C40",
                "values": [[formatted_sync_time]]
            },
            {
                "range": f"{dashboard_tab}!C41",
                "values": [[formatted_transaction_date]]
            }
        ]
        
        LOGGER.info("Updating Dashboard: last sync=%s, most recent transaction=%s", formatted_sync_time, formatted_transaction_date)
        self._service.spreadsheets().values().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={
                "valueInputOption": "USER_ENTERED",
                "data": data
            }
        ).execute()
