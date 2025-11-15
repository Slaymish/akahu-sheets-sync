# Bank Transaction Sync

Automated transaction syncing from BNZ to Google Sheets using Akahu's banking API. Built to run on a Raspberry Pi with minimal resource usage.

## What it does

This script pulls your settled bank transactions from Akahu (a NZ banking aggregator), automatically categorizes them using regex rules, and maintains an append-only ledger in Google Sheets. Think of it as the data pipeline that feeds your budgeting spreadsheets—it handles the boring stuff so your Sheet formulas can focus on the analysis.

**Key features:**
- Incremental sync (only fetches new transactions since last run)
- Automatic categorization via configurable regex rules with amount conditions
- Transfer detection (e.g., moving money between your own accounts)
- Balance reconciliation to catch API drift
- Deduplication using Akahu's stable transaction IDs
- Batch API operations to avoid rate limits

## How it works

```
BNZ Bank → Akahu API → Python Script → Google Sheets
```

The script maintains state in `sync_state.json` so it knows where it left off. Each run:
1. Fetches new settled transactions from Akahu
2. Filters out ignored transactions (tiny interest adjustments, etc.)
3. Applies category rules from your `CategoryMap` sheet tab
4. Detects transfers between your accounts
5. Updates the `Transactions` tab (append new, update changed, delete removed)
6. Optionally reconciles account balances

All monthly summaries and calculations live in your Sheet formulas—the script just maintains the raw transaction ledger.

## Why settled transactions only?

Akahu has separate endpoints for pending and settled transactions. Pending data is mutable and lacks stable IDs, making it unsuitable for an append-only ledger. Settled transactions have permanent IDs that survive bank updates, so that's what we use.

## Google Sheets structure

Your spreadsheet needs these tabs:

**`Transactions`** — The raw ledger (managed by the script)
```
id | date | account | amount | balance | description_raw | merchant_normalised | category | is_transfer | source | imported_at
```

**`CategoryMap`** — Your categorization rules (you edit this)
```
pattern | field | category | priority | amount_condition
```

Rules are applied in priority order (lower number = higher priority). First match wins.

- `pattern`: Regex to match (e.g., "COUNTDOWN")
- `field`: Which field to check (`merchant_normalised` or `description_raw`)
- `category`: The category to assign
- `priority`: Numeric priority (1 = checked first)
- `amount_condition`: Optional. Examples: `>20`, `<=50`, `15 OR 20`, `greater than $100`

**`Monthly_Flow`** (or whatever you call your summary tab) — Your formulas
```
=SUMIFS(Transactions!D:D, Transactions!B:B, ">=2025-01-01", ...)
```

The script never touches your summary tabs. All calculations happen in your Sheet formulas.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Akahu credentials

- Sign up at [my.akahu.nz](https://my.akahu.nz)
- Create an app to get your `app_token`
- Generate a `user_token` for your account
- Connect your BNZ account

### 3. Set up Google Sheets API

- Create a project in [Google Cloud Console](https://console.cloud.google.com)
- Enable the Google Sheets API
- Create a service account and download the JSON key file
- Share your spreadsheet with the service account email

### 4. Configure the script

Create `config.json`:

```json
{
  "akahu_user_token": "user_token_...",
  "akahu_app_token": "app_token_...",
  "google_service_file": "/path/to/service-account.json",
  "spreadsheet_id": "your_spreadsheet_id",
  "lookback_days": 14,
  "perform_reconciliation": true,
  "ignore_rules": [
    {
      "pattern": "INTEREST ADJUSTMENT",
      "field": "description_raw",
      "max_amount": 1.00
    }
  ]
}
```

### 5. Create your Sheet tabs

Create tabs named `Transactions` and `CategoryMap` with the column headers shown above.

## Usage

**Manual run:**
```bash
python main.py
```

**Dry run (preview changes):**
```bash
python main.py --dry-run
```

**Reset sync state (re-fetch all transactions):**
```bash
python main.py --reset-state
```

**Upload category rules from CSV:**
```bash
python main.py --upload-categories CategoryMap.csv
```

**Scheduled sync (cron):**
```bash
# Run every hour
0 * * * * cd /home/pi/bank-finances-sync && /home/pi/bank-finances-sync/venv/bin/python main.py >> sync.log 2>&1
```

## Project structure

```
.
├── main.py                 # Main orchestration script
├── akahu_client.py         # Akahu API wrapper
├── sheets_client.py        # Google Sheets operations
├── categoriser.py          # Rule-based categorization
├── reconciliation.py       # Balance verification
├── state_manager.py        # Sync state persistence
├── ignore_rules.py         # Transaction filtering
├── config.json             # Your credentials (gitignored)
├── sync_state.json         # Last sync timestamp (auto-generated)
└── tests/                  # Unit tests
```

## How deduplication works

Akahu generates stable IDs for each transaction. The script:
1. Reads all existing transaction IDs from the Sheet on startup
2. Compares incoming transactions against this set
3. Updates rows if transaction details changed
4. Appends new transactions
5. Deletes transactions that no longer appear in Akahu's response

In rare cases (<0.1%), banks mutate a transaction so drastically that Akahu assigns a new ID. The script handles this automatically—the old ID gets deleted and the new one gets appended.

## Reconciliation

Each transaction from Akahu includes the account balance after that transaction. The script can optionally verify that the latest balance matches expectations:

```
latest_balance_from_bank ≈ sum_of_all_transactions_in_sheet
```

If drift exceeds $0.10, it logs a warning. This catches API bugs or missing transactions early.

## Technical details

- **Incremental sync:** Uses `sync_state.json` to track the last synced timestamp. Only fetches new transactions since then.
- **Akahu quirk:** The `start` parameter is exclusive, so we subtract 1ms from the last sync time to avoid gaps.
- **Batch operations:** Uses Google Sheets' `batchUpdate` API to avoid rate limits.
- **Transfer detection:** Automatically marks transactions as transfers if they contain keywords like "transfer", "internal", or "BNZ to BNZ".
- **Timezone aware:** All timestamps use UTC with proper timezone handling.

## Testing

```bash
python -m pytest tests/ -v
```

Tests use mock objects to avoid real API calls.

## Future improvements

- Train an ML model on historical transactions for smarter categorization
- Add webhook support for real-time sync
- Local SQLite cache for faster lookups
- Visual diff viewer for modified transactions


