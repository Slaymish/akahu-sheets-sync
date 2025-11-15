# Project TODO

This checklist tracks what the sync service already delivers and which enhancements are next in line.

## Completed
- [x] Automate ingestion of settled transactions from Akahu into Google Sheets with a persisted lookback window.
- [x] Maintain deduplicated transaction history by updating changed rows and deleting entries that disappear upstream.
- [x] Apply rule-based categorisation and transfer detection sourced from the `CategoryMap` sheet.
- [x] Reconcile balances per account (optional) to flag drifts between Akahu data and the sheet ledger.
- [x] Persist the full raw ledger in the `Transactions` tab so spreadsheet formulas stay authoritative.
- [x] Load configuration, credentials, and sync state from local JSON/environment settings for reproducible runs.

## Upcoming
- [ ] Train or integrate an ML-based categorisation model using historical sheet data.
- [ ] Add Akahu webhook ingestion so new settlements sync in near-real time.
- [ ] Introduce a lightweight SQLite cache to accelerate deduplication and reconciliation.
- [ ] Provide a visual diff view (CLI or UI) that highlights modified transactions before updates are applied.
- [ ] Detect and cluster recurring subscription expenses to surface potential savings opportunities.
