# Pi Transaction Sync with Akahu and Google Sheets

## Overview

This project is a lightweight service that runs on a Raspberry Pi (or any Linux machine) and keeps a Google Sheet up to date with your Bank of New Zealand (BNZ) transactions via the Akahu API.

The goal is not budgeting automation but **accurate categorisation and reflection**: your Pi fetches transactions, applies your category-mapping rules, stores raw transactions in a Sheet, and your existing financial views in Google Sheets calculate monthly spending.

Key features:

- Fully automated ingestion of *settled* transactions.
- Robust deduplication using Akahu’s stable transaction IDs.
- Optional reconciliation that verifies account balance equals sum of transactions.
- Manual rule-based transaction categorisation, with future ML categorisation support.
- Full raw ledger stored in Sheets so historical calculations remain transparent.

---

## Architecture

BNZ → Akahu → Raspberry Pi script → Google Sheets API → Your “Life Finances” Sheet

The Pi script:

1. Fetches new settled transactions from Akahu.
2. Normalises fields (merchant name, description).
3. Applies your category rules.
4. Appends new rows into a `Transactions` tab.
5. (Optional) Reconciles balances.
6. Leaves all monthly calculations to your existing Sheet formulas.

---

## Why only settled transactions?

Akahu provides *pending* and *settled* transactions at different endpoints.

Akahu explains that pending data is unstable and lacks identifiers:

- Pending transactions are mutable and should be rebuilt on each fetch.
- Settled transactions have stable Akahu IDs that remain consistent across updates【Akahu docs: Keeping transactions synchronised】.

Since your system is designed for historical reflection, you use **only settled transactions**.

---

## Google Sheets Structure

### 1. `Transactions` (raw ledger, append-only)
Columns:

- `id` (Akahu’s stable transaction ID)
- `date`
- `account`
- `amount`
- `balance`
- `description_raw`
- `merchant_normalised`
- `category`
- `is_transfer`
- `source` (e.g. akahu_bnz)
- `imported_at`

### 2. `CategoryMap`
Columns:

- `pattern` (substring to match)
- `field` (merchant_normalised or description_raw)
- `category`
- `priority` (lower number = matched first)

### 3. `Summary` (your existing monthly view)
Formulas reference the `Transactions` tab, e.g.:

```gs
=SUMIFS(
  Transactions!$C:$C,
  Transactions!$B:$B, ">=" & A1,
  Transactions!$B:$B, "<" & A2,
  Transactions!$G:$G, "Food: Groceries",
  Transactions!$I:$I, FALSE
)

Your Pi script never touches Summary.

⸻

Deduplication Strategy

Akahu states:
	•	Banks do not provide stable transaction identifiers.
	•	Akahu generates their own stable IDs based on transaction attributes.
	•	IDs remain stable unless the bank mutates a transaction beyond recognition (<0.1% cases).

You must therefore:
	•	Treat Akahu’s id as authoritative.
	•	Before inserting any transaction, check whether its id already exists in Transactions.

When a rare mutation event occurs:
	•	A new ID replaces the old one.
	•	The old transaction should be removed.
	•	The new transaction should be inserted.

Your script handles this by:
	1.	Building a set of known IDs from the Sheet at startup.
	2.	Keeping a mapping of IDs → row numbers (optional optimisation).
	3.	If an incoming transaction ID is present, update the row if fields changed.
	4.	If an incoming ID is new, append it.
	5.	If an ID disappears from Akahu’s results for a date range, delete it from the Sheet.

⸻

Reconciliation Strategy

To safeguard against silent drift:
	•	Each settled transaction includes a balance field representing the account balance after that transaction.
	•	Periodically (e.g. once per day), collect the latest transaction for an account and compare:

balance_from_bank == sum_of_all_transactions + opening_balance

If mismatch is detected:
	•	Log an alert.
	•	Optionally trigger a full re-scan for the past N days.

⸻

Handling Date Ranges

Akahu’s API:
	•	Returns dates in UTC.
	•	Accepts ISO 8601 start and end timestamps.
	•	start is exclusive, end is inclusive【Akahu docs: Getting a date range】.

For NZDT example:

?start=2024-12-31T23:59:59.999+13:00
&end=2025-01-01T23:59:59.999+13:00

Your script should:
	•	Maintain a last_imported_at timestamp.
	•	Request new transactions with start=last_imported_at.

Because start is exclusive, set:

start = last_imported_at - 1ms

This prevents missing edge cases.

⸻

Category Mapping

Start simple with rules:

{
  "pattern": "COUNTDOWN",
  "field": "merchant_normalised",
  "category": "Food: Groceries",
  "priority": 10
}

Process:
	1.	Normalise text: uppercase, trim, collapse whitespace.
	2.	Apply rules in ascending priority order.
	3.	First match wins.
	4.	If nothing matches: UNCATEGORISED.

Later, plug in ML:
	•	Train a classifier on your own labelled Transactions dataset.
	•	Use ML only as fallback after explicit rules.

⸻

Script Flow

1. Load configuration
	•	Akahu user token
	•	Akahu app token
	•	Google service account credentials
	•	Mapping of accounts → Google Sheets tab

2. Load existing transaction IDs

Read the id column from the Transactions tab into a Python set.

3. Query Akahu

Use:

GET https://api.akahu.io/v1/transactions?start=...&end=...

Headers:

Authorization: Bearer {{user_token}}
X-Akahu-Id: {{app_token}}

Paginate until cursor.next is null.

4. Filter settled transactions only

Ignore pending endpoint entirely.

5. Normalise + Categorise
	•	Clean merchant name
	•	Apply rules
	•	Set is_transfer if both sides of transfer detected

6. Deduplicate

If ID in set:
	•	Optionally update the row if modified (date/description/amount changes)
	•	Skip otherwise

If ID not in set:
	•	Append new row

7. Reconciliation (optional)

Once per run:
	•	Group transactions by account
	•	Verify the ending balance matches Akahu’s reported balance
	•	If drift detected, log & optionally rebuild N days

⸻

Directory Structure

project-root/
  ├── main.py
  ├── akahu_client.py
  ├── sheets_client.py
  ├── categoriser.py
  ├── reconciliation.py
  ├── config.json
  ├── requirements.txt
  └── README.md


⸻

Installation

1. Install Python dependencies

pip install -r requirements.txt

Suggested requirements.txt:

google-api-python-client
google-auth
google-auth-httplib2
google-auth-oauthlib
requests
python-dateutil
pytz

2. Create Google service account
	•	Enable Google Sheets API
	•	Create service account keys
	•	Share your spreadsheet with the service email

3. Store Akahu tokens in a secure file

Example config.json:

{
  "akahu_user_token": "user_token_here",
  "akahu_app_token": "app_token_here",
  "spreadsheet_id": "your_sheet_id_here"
}


⸻

Running

Manual:

python3 main.py

Cron job (hourly):

0 * * * * /usr/bin/python3 /home/pi/project/main.py >> /home/pi/log.txt 2>&1


⸻

Future Improvements
	•	ML-based category model trained on your personalised data.
	•	Add webhook support to make ingestion realtime.
	•	Local SQLite cache to speed up dedup & reconciliation.
	•	Visual diff viewer for modified transactions.
	•	Add cluster detection for subscription expenses.

⸻

License

MIT — do whatever you want, modify however you like.

Let me know if you'd like a matching `main.py` scaffold or an initial Google Sheets schema file.l
