---
name: nappi-dashboard-update
description: Update the Flight Deck Brewing distribution dashboard with the latest Nappi Distributors daily reports from Google Drive.
---

Update the Flight Deck Brewing Nappi dashboard with any new daily reports.

## How it works

Nappi Distributors emails two PDF reports to nate@flightdeckbrewing.com each weekday evening:
- **"Flight Deck Daily Sales Comp"** (FLIGHTDECK) — product-level sales + inventory
- **"Flight Deck Daily Accounts"** (RANKALLBRW) — account-level order detail

A separate Google Apps Script (managed outside this project) automatically pulls these PDFs from Gmail, uploads them to Google Drive folder `1OG70gPUMeCrYtFGTejqFdx8p1HhOhUt0` ("Nappi Reports"), and creates Google Doc copies (triggering OCR) named `YYYY-MM-DD - REPORTNAME`.

This task simply reads the Google Docs from that Drive folder, parses them, and updates the dashboard. It does NOT touch Gmail.

## Files

All paths are relative to the nappi-dashboard folder inside the user's selected folder. Use `ls /sessions/*/mnt/FD\ Claude\ Projects/nappi-dashboard/` to find the working directory.

- `text/` — cached OCR text files, named `FLIGHTDECK_YYYY-MM-DD.txt` and `RANKALLBRW_YYYY-MM-DD.txt`
- `data/nappi_data.json` — the full data store (JSON keyed by date)
- `data/dashboard_data.json` — compact dashboard data built by `build_dashboard_data.py`
- `dashboard.html` — the dashboard (has `const D = {...};` embedded in a script tag)
- `parse_nappi.py` — Python parser with `parse_sales_comp()`, `parse_accounts()`, `build_daily_snapshot()`
- `build_dashboard_data.py` — builds compact dashboard data from `nappi_data.json` and updates `dashboard.html`. Has `build_dashboard_data(data)` and `update_dashboard_html(dashboard_data, html_path)` functions.
- `nappi_gmail_to_drive.gs` — reference copy of the Google Apps Script

## Workflow

### 1. Check what's already processed
```python
import json
with open('data/nappi_data.json') as f:
    existing = json.load(f)
print("Processed dates:", sorted(existing.keys()))
```

### 2. Search Google Drive for new reports

Use the Google Drive search MCP tool to list documents in the Nappi Reports folder:
```
api_query: '1OG70gPUMeCrYtFGTejqFdx8p1HhOhUt0' in parents and mimeType = 'application/vnd.google-apps.document'
```

Compare document titles (e.g. `2026-03-19 - FLIGHTDECK`) against already-processed dates.

If no new documents exist, report the dashboard is up to date.

### 3. Fetch and parse new reports

For each new date, use the Google Drive fetch MCP tool to get the full document text. Then save and parse:

```python
import sys, os, re, json
sys.path.insert(0, '/path/to/nappi-dashboard')
from parse_nappi import parse_sales_comp, parse_accounts, build_daily_snapshot

# Save text files (the parser handles markdown stripping from Drive OCR)
with open(f'text/FLIGHTDECK_{date_str}.txt', 'w') as f:
    f.write(flightdeck_text)
with open(f'text/RANKALLBRW_{date_str}.txt', 'w') as f:
    f.write(rankallbrw_text)

# Parse
sc_data = parse_sales_comp(text_content=flightdeck_text)
ac_data = parse_accounts(text_content=rankallbrw_text)
snapshot = build_daily_snapshot(sc_data, ac_data, date_str)
```

### 4. Update data store + dashboard

```python
import json
from build_dashboard_data import build_dashboard_data, update_dashboard_html

# Merge into data store
with open('data/nappi_data.json') as f:
    all_data = json.load(f)
all_data[date_str] = snapshot
with open('data/nappi_data.json', 'w') as f:
    json.dump(all_data, f, indent=2)

# Build compact dashboard data and update HTML
dashboard = build_dashboard_data(all_data)
compact = json.dumps(dashboard, separators=(',', ':'))
with open('data/dashboard_data.json', 'w') as f:
    f.write(compact)

update_dashboard_html(dashboard, 'dashboard.html')
```

Note: The dashboard HTML uses `const D = {...};` (not `DATA`). The `update_dashboard_html` function handles the regex replacement correctly.

### 5. Report

- Confirm new date(s) added
- List any products with CRITICAL (≤14 days) or ORDER_NOW (≤21 days) inventory status
- If no new data found, say the dashboard is up to date

## Compact Dashboard Data Format

The dashboard uses a compact JSON format built by `build_dashboard_data.py`. It contains:
- `trend[]` — daily totals: date, mtd, on_hand, accounts, active
- `products{}` — per-SKU trends: name, format, ce_factor, daily snapshots
- `accounts{}` — new_by_date, reorder_watch (5+ report-days since last order), upsell (1-2 product accounts), order_log (last 30 orders)
- `reps{}` — scorecard with mtd, accts, daily, new_accts, trend (up/down/steady), history
- `production{}` — alerts (CRITICAL/ORDER_NOW), velocity, stockout_projections, format_mix
- `totals{}` — latest sales comp totals

## Reference

### Inventory thresholds
- CRITICAL: ≤14 days of inventory
- ORDER_NOW: ≤21 days
- PLAN_PRODUCTION: ≤28 days
- OK: >28 days

### SKU Map
```
45000: P3 Pale Ale 4PK CAN
45003: P3 Pale Ale 1/6 BBL
45005: Subhunter IPA 4PK CAN
45008: Subhunter IPA 1/6 BBL
45010: Wings Hazy IPA 4PK CAN
45013: Wings Hazy IPA 1/6 BBL
45015: Plane Beer Pilsner 6PK CAN
45018: Plane Beer Pilsner 1/6 BBL
45020: Remove Before Flight 4PK CAN
45023: Remove Before Flight 1/6 BBL
45038: Real Maine Italian Pilsner 1/6 BBL
```
