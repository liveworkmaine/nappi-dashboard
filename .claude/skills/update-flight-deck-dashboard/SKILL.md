---
name: update-flight-deck-dashboard
description: >
  Update the Flight Deck Brewing "Mission Control" Nappi dashboard with the latest data.
  Use this skill whenever Nate asks to "update the dashboard", "refresh the dashboard",
  "pull new Nappi data", "update inventory", "refresh inventory numbers",
  "rebuild the dashboard", "update Flight Deck dashboard", or any variation referring to
  refreshing the Flight Deck Brewing distribution dashboard with current data.
  This covers both the Nappi wholesale reports AND the brewery inventory from the
  Google Sheet. If in doubt whether the user means this dashboard vs. another project,
  ask — but if they say "the dashboard" in the context of Flight Deck or brewing, this is it.
---

# Update Flight Deck Dashboard

This skill walks through the complete pipeline to refresh the Flight Deck Brewing
"Mission Control" distribution dashboard with the latest Nappi wholesale data and
brewery inventory counts.

## Project location

All files live in `FD Claude Projects/nappi-dashboard/`. Key files:

| File | Purpose |
|------|---------|
| `data/nappi_data.json` | All Nappi report snapshots (one entry per report date) |
| `data/sku_config.json` | Master product catalog — 15 brands, brand-centric format |
| `data/brewery_inventory.json` | Parsed brewery inventory from Google Sheet |
| `data/inventory_raw.json` | Raw MCP fetch from Google Sheet (intermediate, gitignored) |
| `data/dashboard_data.json` | Compiled dashboard data (output of build script) |
| `text/` | Nappi report text files (FLIGHTDECK_*.txt, RANKALLBRW_*.txt) |
| `parse_nappi.py` | Parses Nappi report text/PDFs into structured data |
| `fetch_inventory.py` | Parses raw Google Sheet data into brewery_inventory.json |
| `build_dashboard_data.py` | Merges all data sources and rebuilds dashboard |
| `dashboard.html` | The dashboard itself (data is embedded inline) |

## The pipeline has three stages

### Stage 1: Fetch new Nappi reports from Google Drive

Nappi sends daily wholesale reports via email. A Google Apps Script automatically
converts these into Google Docs in a Drive folder (ID: `1OG70gPUMeCrYtFGTejqFdx8p1HhOhUt0`).

**To check for and fetch new reports:**

1. Use the Google Drive MCP to search the Nappi Reports folder for documents newer
   than the latest date in `nappi_data.json`. Check the latest date first:
   ```
   Read data/nappi_data.json and find the most recent date key (they're YYYY-MM-DD format).
   ```

2. Search Google Drive folder `1OG70gPUMeCrYtFGTejqFdx8p1HhOhUt0` for files with
   names matching `YYYY-MM-DD - FLIGHTDECK` and `YYYY-MM-DD - RANKALLBRW` that are
   newer than the latest date.

3. For each new date found (needs BOTH a FLIGHTDECK and RANKALLBRW file), fetch the
   document content and save to `text/FLIGHTDECK_YYYY-MM-DD.txt` and
   `text/RANKALLBRW_YYYY-MM-DD.txt`.

4. Run the parser to update nappi_data.json:
   ```bash
   cd "FD Claude Projects/nappi-dashboard" && python3 parse_nappi.py
   ```
   This reads all text files in `text/` and rebuilds `data/nappi_data.json`.

**If no new Nappi reports exist**, that's fine — just say "Nappi data is current
through [date]" and move on to Stage 2.

### Stage 2: Refresh brewery inventory from Google Sheet

Nate does weekly physical inventory counts and enters them into a Google Sheet.
Each weekly count is a new tab named by date (e.g., "3/30", "4/6").

**Spreadsheet ID:** `1L2kCpiYnZOSpsAtb6Myg4fNsPRRzsnXAfwACfuklyac`

1. First, fetch the spreadsheet metadata to find the most recent tab:
   ```
   Use google_sheets_get_spreadsheet_by_id with the spreadsheet ID above.
   The tab names are dates like "3/30", "3/23", etc.
   The most recent tab is the current inventory (it will be the second tab —
   the first is "Nappi Emails" which should be skipped).
   ```

2. Compare the most recent tab against the current `brewery_inventory.json`
   (`last_updated` field). If it's the same, inventory is already current.

3. If there's a newer tab, fetch the data:
   ```
   Use google_sheets_get_data_range on the new tab, range A1:R45.
   This covers the inventory rows (5-29ish) and pricing reference (33+).
   ```

4. Save the raw MCP response as `data/inventory_raw.json`.

5. Run the parser with the tab name:
   ```bash
   python3 fetch_inventory.py --tab "3/30"
   ```
   (Replace "3/30" with the actual tab name.)

**Important parsing details the script handles:**
- Column A has "Beer Style - Brew Date" (e.g., "P3 - 3/23") — sometimes without
  the dash (e.g., "Subhunter 3/23")
- Same beer brand has multiple rows (one per batch) — the script sums them
- Outdoor Walk-In (cols B-E) + Tasting Room (cols G-J) are summed because the
  CONSOLIDATED columns (L-O) return null from the API (they're formulas)
- Brand names are matched to `sku_config.json` via the `inventory_name` field

### Stage 3: Rebuild the dashboard

```bash
cd "FD Claude Projects/nappi-dashboard" && python3 build_dashboard_data.py
```

This script:
- Loads `nappi_data.json` (Nappi wholesale data)
- Loads `sku_config.json` (master brand catalog, brand-centric with 15 brands)
- Loads `brewery_inventory.json` (physical inventory counts)
- For each Nappi SKU, merges brewery on-hand with Nappi on-hand:
  - `brewery_oh` = matching inventory from the Google Sheet
  - `total_available` = `nappi_oh` + `brewery_oh`
  - `days_to_zero` recalculated using `total_available`
- Adds "tasting room only" brands (9 brands not in Nappi)
- Outputs `data/dashboard_data.json` and embeds it into `dashboard.html`

Expected output:
```
Loaded SKU config: 15 brands (6 with Nappi SKUs)
Loaded brewery inventory: 15 brands (as of YYYY-MM-DD)
Dashboard data: ~117 KB
Dashboard HTML updated: ~163 KB
```

## After the update

Tell Nate:
- What date the Nappi data now covers (and how many new report days were added, if any)
- What date the brewery inventory is from
- Any alerts: BREW_NOW items, low-stock items, or anything that changed significantly
- If a brand appeared in the inventory sheet but wasn't matched to sku_config.json
  (the script prints a WARNING for this — it means a new brand needs to be added)

## Troubleshooting

**"No sku_config.json found"** — The brand-centric config is missing. It should be at
`data/sku_config.json` with a `brands` key containing all 15 brands.

**"No brewery_inventory.json found"** — Run Stage 2 first to fetch from Google Sheets.

**Parser finds 0 products** — The Nappi text file format may have changed. Check the
raw text in `text/` to see if the layout shifted.

**New beer brand in inventory sheet** — Add it to `data/sku_config.json` under `brands`
with the appropriate `inventory_name` matching column A in the sheet.
