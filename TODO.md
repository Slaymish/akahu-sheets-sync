# Project TODO

This checklist tracks what the sync service already delivers and which enhancements are next in line.

## Completed
- [x] Automate ingestion of settled transactions from Akahu into Google Sheets with a persisted lookback window.
- [x] Maintain deduplicated transaction history by updating changed rows and deleting entries that disappear upstream.
- [x] Apply rule-based categorisation and transfer detection sourced from the `CategoryMap` sheet.
- [x] Reconcile balances per account (optional) to flag drifts between Akahu data and the sheet ledger.
- [x] Persist the full raw ledger in the `Transactions` tab so spreadsheet formulas stay authoritative.
- [x] Load configuration, credentials, and sync state from local JSON/environment settings for reproducible runs.
- [x] Add a `--dry-run` CLI flag that prints the planned sheet mutations without applying them.

## Upcoming

### Core reliability / correctness

- [ ] Implement robust retry and backoff for Akahu and Google Sheets API errors, including rate limit handling.
- [ ] Add structured logging (machine readable) plus a human friendly log summary for each run.
- [ ] Add a `healthcheck` / `--verify` mode that only:
- [ ]  - validates credentials and connectivity
- [ ]  - checks the target spreadsheet structure is as expected
- [ ]  - reports current sync window and last imported transaction
- [ ] Harden reconciliation:
- [ ]  - log per account drift deltas
- [ ]  - expose a clear “safe to rebuild last N days” hint
- [ ] Add a one-off “backfill” command to re-sync a historical date range into the sheet.
- [ ] Handle Akahu’s earliest-available-date boundary explicitly and log when you hit it.
- [ ] Formalise secret management (service account keys, Akahu tokens) with a small guide for storing them safely on the Pi.

### Data model / UX

- [x] Add a simple “ignore rule” system to drop noisy transactions (for example, tiny interest adjustments) before they hit the sheet.
- [ ] Support manual override of categories in the `Transactions` tab without them being re-written by the script.
- [ ] Add a self-check that warns if required sheet tabs or columns are missing or renamed.
- [ ] Provide a visual diff view (CLI or UI) that highlights modified transactions before updates are applied.
      (Nice to have, but after the reliability bits.)

### Smarter features

- [ ] Train or integrate an ML-based categorisation model using historical sheet data, behind a feature flag.
- [ ] Surface categorisation confidence scores alongside each transaction to aid manual reviews.
- [ ] Detect and cluster recurring subscription expenses to surface potential savings opportunities.
- [ ] Introduce a lightweight SQLite cache to accelerate deduplication, reconciliation, and drift detection.
- [ ] Add Akahu webhook ingestion so new settlements sync in near-real time, falling back to polling if webhooks fail.
- [ ] Export a summary CSV (per account + category totals) after each sync run for easy sharing.
- [ ] Extend tests to cover edge cases such as:
- [ ]  - negative transaction amounts and refunds
- [ ]  - timezone rollovers
- [ ]  - category rule collisions and priority ordering
