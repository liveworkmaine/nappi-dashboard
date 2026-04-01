#!/usr/bin/env python3
"""
Fetch and parse brewery inventory from the Google Sheet.

Two modes of operation:
  1. COWORK MODE (default): Reads data/inventory_raw.json (pre-fetched via
     Google Sheets MCP in a Cowork session) and parses it into
     data/brewery_inventory.json.

  2. MANUAL MODE: Pass --raw <file> to parse a specific raw JSON file.

The raw JSON format matches the Zapier Google Sheets MCP "get_data_range"
output: a list of row objects with COL_A through COL_O keys.

Workflow:
  1. In Cowork: use Google Sheets MCP to fetch the latest tab → save as
     data/inventory_raw.json
  2. Run: python3 fetch_inventory.py
  3. Output: data/brewery_inventory.json

The parser:
  - Reads column A ("Beer Style - Brew Date") to extract brand names
  - Sums all batch rows for the same brand
  - Combines Outdoor Walk-In (cols B-E) + Tasting Room (cols G-J) since
    the CONSOLIDATED columns (L-O) come back as null from the API
  - Matches brand names to sku_config.json brand keys via inventory_name
"""

import json
import os
import re
import sys
from collections import defaultdict


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')


def load_sku_config():
    """Load the master SKU config and build inventory_name → brand_key lookup."""
    config_path = os.path.join(DATA_DIR, 'sku_config.json')
    with open(config_path) as f:
        config = json.load(f)

    # Build reverse lookup: lowercase inventory_name → brand_key
    inv_to_brand = {}
    for brand_key, brand in config.get('brands', {}).items():
        inv_name = brand.get('inventory_name', '')
        if inv_name:
            inv_to_brand[inv_name.strip().lower()] = brand_key

    return config, inv_to_brand


def parse_float(val):
    """Safely parse a numeric value, treating None/empty as 0."""
    if val is None or val == '' or val == ' ':
        return 0.0
    try:
        return float(str(val).strip().replace(',', ''))
    except (ValueError, TypeError):
        return 0.0


def extract_brand_name(cell_a):
    """
    Extract the brand name from "Beer Style - Brew Date" or "Beer Style Brew Date".

    Examples:
      "P3 - 3/23"             → "P3"
      "Remove Before Flight - 2/10" → "Remove Before Flight"
      "Subhunter 3/23"        → "Subhunter"  (note: no dash)
      "Space-A - 2/17"        → "Space-A"
    """
    if not cell_a or not cell_a.strip():
        return None

    text = cell_a.strip()

    # Try "Brand - Date" pattern first (most common)
    match = re.match(r'^(.+?)\s*-\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)$', text)
    if match:
        return match.group(1).strip()

    # Try "Brand Date" without dash (e.g. "Subhunter 3/23")
    match = re.match(r'^(.+?)\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)$', text)
    if match:
        return match.group(1).strip()

    # If no date pattern found, skip (probably a header or empty)
    return None


def parse_inventory_rows(raw_rows):
    """
    Parse raw sheet rows into aggregated per-brand inventory.

    Returns dict: { brand_display_name: { kegs_sixth, kegs_half, cases_16oz, cases_12oz } }
    """
    brand_totals = defaultdict(lambda: {
        'kegs_sixth': 0.0,
        'kegs_half': 0.0,
        'cases_16oz': 0.0,
        'cases_12oz': 0.0,
    })

    for row in raw_rows:
        cell_a = row.get('COL_A')
        brand_name = extract_brand_name(cell_a)
        if not brand_name:
            continue

        # Outdoor Walk-In: B=1/6bbl, C=1/2bbl, D=16oz cases, E=12oz cases
        outdoor_sixth = parse_float(row.get('COL_B'))
        outdoor_half = parse_float(row.get('COL_C'))
        outdoor_16oz = parse_float(row.get('COL_D'))
        outdoor_12oz = parse_float(row.get('COL_E'))

        # Tasting Room: G=1/6bbl, H=1/2bbl, I=16oz cases, J=12oz cases
        tasting_sixth = parse_float(row.get('COL_G'))
        tasting_half = parse_float(row.get('COL_H'))
        tasting_16oz = parse_float(row.get('COL_I'))
        tasting_12oz = parse_float(row.get('COL_J'))

        # Sum both locations
        totals = brand_totals[brand_name]
        totals['kegs_sixth'] += outdoor_sixth + tasting_sixth
        totals['kegs_half'] += outdoor_half + tasting_half
        totals['cases_16oz'] += outdoor_16oz + tasting_16oz
        totals['cases_12oz'] += outdoor_12oz + tasting_12oz

    return dict(brand_totals)


def match_brands_to_config(brand_totals, inv_to_brand):
    """
    Match parsed brand names to sku_config brand keys.
    Returns dict keyed by brand_key with inventory data.
    Also returns a list of unmatched brand names for debugging.
    """
    matched = {}
    unmatched = []

    for brand_name, totals in brand_totals.items():
        brand_key = inv_to_brand.get(brand_name.strip().lower())
        if brand_key:
            # Round to reasonable precision
            matched[brand_key] = {
                'kegs_sixth': round(totals['kegs_sixth'], 1),
                'kegs_half': round(totals['kegs_half'], 1),
                'cases_16oz': round(totals['cases_16oz'], 2),
                'cases_12oz': round(totals['cases_12oz'], 2),
            }
        else:
            unmatched.append(brand_name)
            # Still include it with a best-guess key
            fallback_key = re.sub(r'[^a-z0-9]+', '_', brand_name.lower()).strip('_')
            matched[fallback_key] = {
                'kegs_sixth': round(totals['kegs_sixth'], 1),
                'kegs_half': round(totals['kegs_half'], 1),
                'cases_16oz': round(totals['cases_16oz'], 2),
                'cases_12oz': round(totals['cases_12oz'], 2),
            }

    return matched, unmatched


def detect_source_tab(raw_data):
    """Try to detect the source tab name from the raw data metadata."""
    if isinstance(raw_data, dict):
        # Check for execution metadata
        execution = raw_data.get('execution', {})
        params = execution.get('params', {})
        return params.get('worksheet', None)
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Parse brewery inventory from Google Sheet data')
    parser.add_argument('--raw', default=os.path.join(DATA_DIR, 'inventory_raw.json'),
                        help='Path to raw JSON from Google Sheets MCP (default: data/inventory_raw.json)')
    parser.add_argument('--output', default=os.path.join(DATA_DIR, 'brewery_inventory.json'),
                        help='Output path (default: data/brewery_inventory.json)')
    parser.add_argument('--tab', default=None,
                        help='Override source tab name (e.g. "3/30")')
    args = parser.parse_args()

    # Load raw data
    if not os.path.exists(args.raw):
        print(f"ERROR: Raw data file not found: {args.raw}")
        print("Run the Google Sheets MCP fetch in Cowork first, or provide --raw <file>")
        sys.exit(1)

    with open(args.raw) as f:
        raw_data = json.load(f)

    # Extract the row array — handle both direct array and MCP response wrapper
    if isinstance(raw_data, list):
        raw_rows = raw_data
    elif isinstance(raw_data, dict) and 'results' in raw_data:
        raw_rows = raw_data['results']
    else:
        print(f"ERROR: Unexpected raw data format. Expected list or dict with 'results' key.")
        sys.exit(1)

    # Detect source tab
    source_tab = args.tab
    if not source_tab:
        source_tab = detect_source_tab(raw_data)

    # Load SKU config
    config, inv_to_brand = load_sku_config()

    # Parse and aggregate
    brand_totals = parse_inventory_rows(raw_rows)
    matched, unmatched = match_brands_to_config(brand_totals, inv_to_brand)

    if unmatched:
        print(f"WARNING: {len(unmatched)} brand(s) not found in sku_config.json:")
        for name in unmatched:
            print(f"  - '{name}'")

    # Determine last_updated date from tab name
    last_updated = source_tab or 'unknown'
    # Convert tab name like "3/30" to ISO-ish date (assume current year)
    if source_tab and re.match(r'^\d{1,2}/\d{1,2}$', source_tab):
        from datetime import date
        parts = source_tab.split('/')
        month, day = int(parts[0]), int(parts[1])
        year = date.today().year
        last_updated = f"{year}-{month:02d}-{day:02d}"

    # Build output
    output = {
        'last_updated': last_updated,
        'source_tab': source_tab or 'unknown',
        'brands': matched,
    }

    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Brewery inventory saved: {args.output}")
    print(f"  Source tab: {source_tab or 'unknown'}")
    print(f"  Last updated: {last_updated}")
    print(f"  Brands: {len(matched)}")
    for brand_key, inv in sorted(matched.items()):
        total_units = inv['kegs_sixth'] + inv['kegs_half'] + inv['cases_16oz'] + inv['cases_12oz']
        print(f"    {brand_key}: {inv['kegs_sixth']} sixth, {inv['kegs_half']} half, "
              f"{inv['cases_16oz']} 16oz, {inv['cases_12oz']} 12oz  (total: {total_units:.1f})")


if __name__ == '__main__':
    main()
