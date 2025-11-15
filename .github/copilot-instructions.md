# Copilot Instructions for Bank Finances Sync

## Project Overview

This is a **Raspberry Pi transaction sync service** that fetches settled transactions from Akahu (BNZ bank aggregator) and maintains an append-only ledger in Google Sheets. The system prioritizes **accurate historical reflection** over real-time budgeting, with all monthly calculations living in Sheet formulas.

**Core principle**: Script writes raw transactions; Sheets does the math.

## Architecture & Data Flow

```
BNZ → Akahu API → Python sync script → Google Sheets API → "Transactions" tab
                                                           ↓
                                                    "Summary" tab (formulas only)
```

### Key Components

- **`main.py`**: Orchestrates sync workflow with `--dry-run` support
- **`akahu_client.py`**: Fetches settled transactions (not pending) from Akahu API
- **`sheets_client.py`**: Manages Google Sheets read/write operations
- **`categoriser.py`**: Priority-based regex rules from `CategoryMap` sheet tab
- **`ignore_rules.py`**: Pre-filters noise (e.g. tiny interest adjustments) before sheet writes
- **`state_manager.py`**: Persists `last_synced_at` timestamp to `sync_state.json`
- **`reconciliation.py`**: Optional balance drift detection (per-account)

### State Management

- **Incremental sync**: Uses `last_synced_at - 1ms` as `start` (Akahu's `start` is exclusive)
- **Deduplication**: Akahu transaction IDs are treated as authoritative; existing rows updated if changed
- **Row deletion**: Transactions no longer returned by Akahu are removed from sheet

## Google Sheets Structure

### `Transactions` Tab (Raw Ledger)
Columns: `id | date | account | amount | balance | description_raw | merchant_normalised | category | is_transfer | source | imported_at`

- `id`: Akahu's stable transaction ID (used for deduplication)
- `balance`: Post-transaction account balance from bank (used in reconciliation)
- `is_transfer`: Auto-detected using keywords like "transfer", "internal", "bnz"

### `CategoryMap` Tab (Rules)
Columns: `pattern | field | category | priority | amount_condition`

- Rules are sorted by ascending `priority` (lower = higher precedence)
- First match wins; unmatched → `"Uncategorised"`
- `field` defaults to `merchant_normalised`, can also be `description_raw`
- `amount_condition` supports flexible formats:
  - Operators: `>20`, `<=50`, `>=100`
  - Natural language: `greater than $50`, `at least 100`, `no more than 20`
  - Exact values: `15`, `$42.50`
  - Multiple values: `15 OR 20`, `$5 or $10`
  - All comparisons use **absolute values** (negatives become positive)

### `Summary` Tab
Never touched by script. Uses `SUMIFS` referencing `Transactions!` ranges.

## Critical Conventions

### Only Settled Transactions
**Never fetch pending transactions**. Akahu docs state pending data is mutable and lacks stable IDs. Always use `/transactions` endpoint with settled filter.

### Timezone Handling
- Akahu returns UTC timestamps
- Script uses `datetime.now(timezone.utc)` for `imported_at`
- Date ranges use ISO 8601 with timezone offsets (e.g., `+13:00` for NZDT)

### Transaction Mutations
When Akahu mutates a transaction beyond recognition (<0.1% cases):
- Old ID disappears → deleted from sheet
- New ID appears → appended as new row
- Handled automatically via `seen_ids` set in `main.py`

### Ignore Rules Config
In `config.json`:
```json
{
  "ignore_rules": [
    {
      "pattern": "INTEREST ADJUSTMENT",
      "field": "description_raw",
      "max_amount": 1.00
    }
  ]
}
```
Matched transactions are logged but **never written to sheet**.

## Developer Workflows

### Running Sync
Entry point is `run.py` (not `main.py` directly). It sets up the Python path before importing.

```bash
# Dry run (preview mutations without applying)
python run.py --dry-run

# Live sync
python run.py

# Reset state and re-fetch from lookback window
python run.py --reset-state

# Upload category rules from CSV to sheet
python run.py --upload-categories data/CategoryMap.csv
```

**Credentials**: Script checks `GOOGLE_APPLICATION_CREDENTIALS` env var first, falls back to `google_service_file` in config.
**Config override**: Set `SYNC_CONFIG` env var to use non-default config path.

### Testing
Tests use **stub modules** (see `tests/conftest.py`) to avoid requiring `google-api-python-client` or `requests` at import time.

```bash
# Run all tests
python -m pytest tests/

# Specific test
python -m pytest tests/test_categoriser.py -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

Tests are **unit-focused**: each module tested in isolation with mocked I/O.

### Configuration
Edit `config.json`:
- `lookback_days`: Fallback window when `sync_state.json` is missing
- `perform_reconciliation`: Set `true` to log balance drift warnings
- `spreadsheet_id`: Your Google Sheets ID (from URL)

Credentials:
- **Akahu**: `akahu_user_token` + `akahu_app_token` (get from https://my.akahu.nz)
- **Google**: Service account JSON path via `GOOGLE_APPLICATION_CREDENTIALS`

## Code Patterns

### Adding New Transaction Fields
1. Update `TRANSACTION_HEADERS` in `sheets_client.py`
2. Extend `AkahuTransaction.to_row()` method
3. Update `SheetTransaction` parsing (pad rows to match header count)
4. Add test coverage in `tests/test_akahu_client.py`

### Adding Categorization Rules
Rules are **pulled from sheet**, not code. To add logic-based categorization:
1. Update `Categoriser.categorise()` to check transaction dict
2. Keep rule-based matching first (explicit rules override logic)
3. Test in `tests/test_categoriser.py`

### Extending Ignore Rules
Modify `IgnoreRule.matches()` in `ignore_rules.py`. Supports:
- Regex matching on any `AkahuTransaction` field
- Optional `min_amount` / `max_amount` bounds (raw amounts, not absolute)
- Case-insensitive by default

Config example:
```json
{
  "pattern": "INTEREST ADJUSTMENT",
  "field": "description_raw",
  "max_amount": 1.00
}
```

## Common Pitfalls

1. **Don't mutate `Summary` tab** – all aggregation lives in Sheet formulas
2. **Akahu `start` is exclusive** – always subtract 1ms from `last_synced_at`
3. **Reconciliation uses latest balance** – sorts by date to find most recent `balance` field
4. **Tests need stubs loaded** – `conftest.py` installs fake `requests` and `googleapiclient` modules
5. **Row indices are 1-based** – Google Sheets API uses 1-based indexing (header = row 1, data starts row 2)

## Future ML Integration

README mentions eventual ML categorization. Intended approach:
- Train on historical `Transactions` tab (labeled data)
- Use as fallback after explicit rules fail
- Store model locally (e.g. `model.pkl`)
- Add confidence scores as new column

Not yet implemented. See `TODO.md` for full roadmap.

## Related Documentation

- **README.md**: Full architectural rationale, API quirks, reconciliation strategy
- **TODO.md**: Planned features (retry logic, backfill command, SQLite caching)
- **config.json**: Example configuration with all supported fields
