#!/usr/bin/env python3
"""
Parse Toast POS monthly ProductMix exports for Flight Deck Brewing.

Reads monthly zip files from the QBO and Toast Reports folder, parses Items.csv
and All levels.csv, maps Toast item names → brand keys, and outputs
data/toast_data.json with monthly granularity per brand for both Brunswick
tasting room and MMM seasonal location.

Pour size → volume conversion (from All levels.csv modifier rows):
  - "7oz" = 7 oz
  - "13oz" / "13.5oz" = 13.5 oz (standard pour)
  - "First Class" = ~16 oz (premium pour)
  - "Can Pour" = 16 oz (selling a can over the counter)
  - "FCC MS" = 5 oz (flight-card mini pour, ignore or count as 5oz)
  1 sixtel (1/6 BBL) = 661 oz ≈ 49 × 13.5oz pours
"""

import csv
import io
import json
import os
import re
import sys
import zipfile
from calendar import monthrange
from collections import defaultdict
from datetime import datetime


SIXTEL_OZ = 661.0

# Pour size name → ounces
POUR_SIZE_OZ = {
    '7oz': 7.0,
    '13oz': 13.5,
    '13.5oz': 13.5,
    'first class': 16.0,
    'can pour': 16.0,
    'fcc ms': 5.0,
}


def load_sku_config():
    """Load sku_config.json and build Toast name → brand_key lookup."""
    base = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base, 'data', 'sku_config.json')
    with open(config_path) as f:
        config = json.load(f)
    return config


def build_toast_name_map(config):
    """
    Build a case-insensitive lookup: normalized Toast item name → brand_key.
    Includes regular names, HH names, and Industry names.
    """
    name_map = {}
    for brand_key, brand in config.get('brands', {}).items():
        for name in brand.get('toast_names', []):
            name_map[name.strip().upper()] = brand_key
        for name in brand.get('toast_names_long', []):
            name_map[name.strip().upper()] = brand_key
        for name in brand.get('hh_names', []):
            name_map[name.strip().upper()] = brand_key
        for name in brand.get('industry_names', []):
            name_map[name.strip().upper()] = brand_key
    return name_map


def build_exclude_patterns(config):
    """Build list of exclusion prefixes (uppercased) from config."""
    return [p.strip().upper() for p in config.get('exclude_toast', [])]


def is_excluded(item_name, exclude_patterns):
    """Check if an item name matches any exclusion pattern."""
    upper = item_name.strip().upper()
    for pat in exclude_patterns:
        if upper.startswith(pat) or pat in upper:
            return True
    return False


def match_brand(item_name, name_map, exclude_patterns):
    """
    Try to match an item name to a brand_key.
    Returns brand_key or None if excluded or unmatched.
    """
    if is_excluded(item_name, exclude_patterns):
        return None
    upper = item_name.strip().upper()
    # Direct match
    if upper in name_map:
        return name_map[upper]
    # Try stripping trailing whitespace / quotes
    cleaned = upper.strip('"').strip()
    if cleaned in name_map:
        return name_map[cleaned]
    return None


def parse_items_csv(csv_content, name_map, exclude_patterns, sales_category_filter):
    """
    Parse Items.csv content. Returns dict of brand_key → {qty_sold, gross_sales}.
    sales_category_filter: "Draft Beer" for Brunswick, "Bottled Beer" for MMM.
    """
    brands = defaultdict(lambda: {'qty_sold': 0, 'gross_sales': 0.0})
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        cat = (row.get('Sales Category') or '').strip()
        if cat != sales_category_filter:
            continue
        item_name = (row.get('Item') or '').strip()
        brand_key = match_brand(item_name, name_map, exclude_patterns)
        if brand_key is None:
            continue
        try:
            qty = float(row.get('Qty sold', 0) or 0)
            gross = float(row.get('Gross sales', 0) or 0)
        except (ValueError, TypeError):
            continue
        brands[brand_key]['qty_sold'] += qty
        brands[brand_key]['gross_sales'] += gross

    return dict(brands)


def parse_all_levels_csv(csv_content, name_map, exclude_patterns, sales_category_filter):
    """
    Parse All levels.csv for pour-size breakdown.
    Returns dict of brand_key → {pour_size → qty_sold}.
    Only processes Type="modifier" rows where the modifier name is a known pour size.
    Also returns menuItem-level qty for brands (as fallback).
    """
    pour_breakdown = defaultdict(lambda: defaultdict(float))
    menu_item_qty = defaultdict(float)

    reader = csv.DictReader(io.StringIO(csv_content))
    for row in reader:
        row_type = (row.get('Type') or '').strip()

        # Get the item name (column varies by row type)
        item_col = row.get('Item, open item') or row.get('Item') or ''
        item_name = item_col.strip()

        if row_type == 'menuItem':
            cat = (row.get('Sales Category') or '').strip()
            if cat != sales_category_filter:
                continue
            brand_key = match_brand(item_name, name_map, exclude_patterns)
            if brand_key:
                try:
                    qty = float(row.get('Qty sold', 0) or 0)
                except (ValueError, TypeError):
                    qty = 0
                menu_item_qty[brand_key] += qty

        elif row_type == 'modifier':
            # Modifier row — check if the modifier name is a pour size
            modifier_name = (row.get('Modifiers, special requests') or '').strip()
            pour_key = modifier_name.lower().strip()
            if pour_key not in POUR_SIZE_OZ:
                continue
            # The item_name here is the parent beer
            brand_key = match_brand(item_name, name_map, exclude_patterns)
            if brand_key is None:
                continue
            try:
                qty = float(row.get('Qty sold', 0) or 0)
            except (ValueError, TypeError):
                continue
            pour_breakdown[brand_key][pour_key] += qty

    return dict(pour_breakdown), dict(menu_item_qty)


def compute_brand_metrics(items_data, pour_data, menu_qty, days_in_period):
    """
    Combine Items.csv totals with All levels.csv pour breakdown.
    Returns dict of brand_key → metrics.
    """
    all_brands = set(items_data.keys()) | set(pour_data.keys()) | set(menu_qty.keys())
    result = {}

    for brand_key in sorted(all_brands):
        item_info = items_data.get(brand_key, {})
        pours = pour_data.get(brand_key, {})

        # qty_sold from Items.csv (includes regular + HH + Industry aggregated)
        qty_sold = item_info.get('qty_sold', 0) or menu_qty.get(brand_key, 0)

        # Calculate total ounces from pour breakdown
        total_oz = 0.0
        pour_counts = {}
        for pour_key, count in pours.items():
            oz = POUR_SIZE_OZ.get(pour_key, 13.5)
            total_oz += count * oz
            pour_counts[pour_key] = round(count)

        # If no pour breakdown available (like MMM cans), estimate from qty
        if total_oz == 0 and qty_sold > 0:
            # MMM sells cans — assume 16oz per unit
            total_oz = qty_sold * 16.0
            pour_counts['can_pour'] = round(qty_sold)

        daily_oz = total_oz / days_in_period if days_in_period > 0 else 0
        daily_kegs = daily_oz / SIXTEL_OZ

        result[brand_key] = {
            'qty_sold': round(qty_sold),
            'gross_sales': round(item_info.get('gross_sales', 0), 2),
            'total_oz': round(total_oz, 1),
            'daily_oz': round(daily_oz, 1),
            'daily_kegs_equiv': round(daily_kegs, 3),
            'pour_breakdown': pour_counts,
        }

    return result


def parse_zip_file(zip_path, name_map, exclude_patterns, is_mmm=False):
    """
    Parse a single monthly ProductMix zip file.
    Returns brand metrics dict for that month.
    """
    sales_cat = 'Bottled Beer' if is_mmm else 'Draft Beer'

    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = zf.namelist()

        # Find Items.csv and All levels.csv
        items_file = None
        all_levels_file = None
        for n in names:
            lower = n.lower()
            if lower == 'items.csv' or lower.endswith('/items.csv'):
                items_file = n
            if 'all levels' in lower and lower.endswith('.csv'):
                all_levels_file = n

        if not items_file:
            print(f"  WARNING: No Items.csv found in {zip_path}")
            return {}, 0

        items_content = zf.read(items_file).decode('utf-8-sig')
        items_data = parse_items_csv(items_content, name_map, exclude_patterns, sales_cat)

        pour_data = {}
        menu_qty = {}
        if all_levels_file:
            al_content = zf.read(all_levels_file).decode('utf-8-sig')
            pour_data, menu_qty = parse_all_levels_csv(
                al_content, name_map, exclude_patterns, sales_cat
            )

        # Calculate total pours from Items.csv (all Draft/Bottled Beer items, including non-FD)
        total_pours = 0
        reader = csv.DictReader(io.StringIO(items_content))
        for row in reader:
            cat = (row.get('Sales Category') or '').strip()
            if cat == sales_cat:
                try:
                    total_pours += float(row.get('Qty sold', 0) or 0)
                except (ValueError, TypeError):
                    pass

        return items_data, pour_data, menu_qty, round(total_pours)


def extract_month_from_filename(filename):
    """
    Extract YYYY-MM from filename like ProductMix_2024-10-01_2024-10-31.zip
    Returns (year-month string, days_in_period).
    """
    match = re.search(r'ProductMix_(\d{4})-(\d{2})-(\d{2})_(\d{4})-(\d{2})-(\d{2})', filename)
    if not match:
        return None, 0
    year, month = int(match.group(1)), int(match.group(2))
    end_day = int(match.group(6))
    start_day = int(match.group(3))
    days_in_period = end_day - start_day + 1
    # Also use actual calendar days as sanity check
    _, cal_days = monthrange(year, month)
    # Use the smaller of actual range or calendar days
    days = min(days_in_period, cal_days)
    return f"{year:04d}-{month:02d}", max(days, 1)


def find_toast_zips(reports_dir):
    """
    Find all monthly ProductMix zip files.
    Returns two lists: (brunswick_files, mmm_files) as (path, month, days) tuples.
    Skips the aggregate file (wide date range).
    """
    brunswick = []
    mmm = []

    for filename in sorted(os.listdir(reports_dir)):
        if not filename.startswith('ProductMix_') or not filename.endswith('.zip'):
            continue

        # Skip aggregate file (spans multiple months)
        match = re.search(r'ProductMix_(\d{4})-(\d{2})-\d{2}_(\d{4})-(\d{2})-\d{2}', filename)
        if match:
            start_ym = (int(match.group(1)), int(match.group(2)))
            end_ym = (int(match.group(3)), int(match.group(4)))
            if start_ym != end_ym:
                print(f"  Skipping aggregate file: {filename}")
                continue

        full_path = os.path.join(reports_dir, filename)
        is_mmm = '- MMM' in filename or '- mmm' in filename

        # Strip MMM suffix before extracting month
        clean_name = filename.replace(' - MMM', '').replace(' - mmm', '')
        month_str, days = extract_month_from_filename(clean_name)
        if month_str is None:
            continue

        if is_mmm:
            mmm.append((full_path, month_str, days, filename))
        else:
            brunswick.append((full_path, month_str, days, filename))

    return brunswick, mmm


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    # Find reports directory — check multiple possible locations
    candidates = [
        os.path.join(base, '..', '..', 'FD Payroll & Financial Analysis', 'QBO and Toast Reports'),
        os.path.join(base, '..', 'FD Payroll & Financial Analysis', 'QBO and Toast Reports'),
        '/sessions/determined-blissful-johnson/mnt/FD Payroll & Financial Analysis/QBO and Toast Reports',
    ]
    reports_dir = None
    for c in candidates:
        if os.path.isdir(c):
            reports_dir = c
            break
    if reports_dir is None:
        reports_dir = candidates[0]  # for error message
    if not os.path.isdir(reports_dir):
        print(f"ERROR: Reports directory not found. Looked in:\n  {reports_dir}")
        sys.exit(1)

    print(f"Reports dir: {reports_dir}")

    # Load config
    config = load_sku_config()
    name_map = build_toast_name_map(config)
    exclude_patterns = build_exclude_patterns(config)
    print(f"Loaded {len(name_map)} Toast name mappings, {len(exclude_patterns)} exclusion patterns")

    # Find zip files
    brunswick_files, mmm_files = find_toast_zips(reports_dir)
    print(f"Found {len(brunswick_files)} Brunswick files, {len(mmm_files)} MMM files")

    # Parse Brunswick files
    brunswick_months = {}
    for zip_path, month_str, days, filename in brunswick_files:
        print(f"  Parsing Brunswick {month_str} ({filename})...")
        result = parse_zip_file(zip_path, name_map, exclude_patterns, is_mmm=False)
        if len(result) == 4:
            items_data, pour_data, menu_qty, total_pours = result
        else:
            continue
        brand_metrics = compute_brand_metrics(items_data, pour_data, menu_qty, days)
        brunswick_months[month_str] = {
            'days_in_period': days,
            'total_pours': total_pours,
            'brands': brand_metrics,
        }

    # Parse MMM files
    mmm_months = {}
    for zip_path, month_str, days, filename in mmm_files:
        print(f"  Parsing MMM {month_str} ({filename})...")
        result = parse_zip_file(zip_path, name_map, exclude_patterns, is_mmm=True)
        if len(result) == 4:
            items_data, pour_data, menu_qty, total_pours = result
        else:
            continue
        brand_metrics = compute_brand_metrics(items_data, pour_data, menu_qty, days)
        mmm_months[month_str] = {
            'days_in_period': days,
            'total_pours': total_pours,
            'brands': brand_metrics,
        }

    # Determine trailing_30d (most recent month) and same_month_last_year
    sorted_months = sorted(brunswick_months.keys())
    trailing_30d = None
    same_month_ly = None
    if sorted_months:
        latest_month = sorted_months[-1]
        trailing_30d = brunswick_months[latest_month]
        trailing_30d['month'] = latest_month

        # Same month last year
        year, month = int(latest_month[:4]), int(latest_month[5:7])
        ly_key = f"{year - 1:04d}-{month:02d}"
        if ly_key in brunswick_months:
            same_month_ly = brunswick_months[ly_key]
            same_month_ly['month'] = ly_key

    # Build output
    output = {
        'generated': datetime.now().strftime('%Y-%m-%d'),
        'brunswick': {
            'months': brunswick_months,
            'trailing_30d': trailing_30d,
            'same_month_last_year': same_month_ly,
        },
        'mmm': {
            'months': mmm_months,
        },
    }

    # Write output
    out_path = os.path.join(base, 'data', 'toast_data.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {os.path.getsize(out_path) / 1024:.1f} KB to {out_path}")

    # Summary
    print(f"\n=== BRUNSWICK SUMMARY ===")
    for m in sorted_months:
        data = brunswick_months[m]
        n_brands = len(data['brands'])
        total_qty = sum(b['qty_sold'] for b in data['brands'].values())
        print(f"  {m}: {data['total_pours']:,} total pours, {total_qty:,} FD pours, {n_brands} brands, {data['days_in_period']}d")

    mmm_sorted = sorted(mmm_months.keys())
    if mmm_sorted:
        print(f"\n=== MMM SUMMARY ===")
        for m in mmm_sorted:
            data = mmm_months[m]
            n_brands = len(data['brands'])
            total_qty = sum(b['qty_sold'] for b in data['brands'].values())
            print(f"  {m}: {data['total_pours']:,} total pours, {total_qty:,} FD units, {n_brands} brands, {data['days_in_period']}d")

    # Print latest month brand breakdown
    if trailing_30d:
        print(f"\n=== LATEST MONTH ({trailing_30d['month']}) BRAND BREAKDOWN ===")
        brands_sorted = sorted(
            trailing_30d['brands'].items(),
            key=lambda x: x[1]['qty_sold'],
            reverse=True
        )
        for bk, bdata in brands_sorted:
            daily_k = bdata['daily_kegs_equiv']
            print(f"  {bk:30s}  {bdata['qty_sold']:5d} pours  {daily_k:.2f} kegs/day  {bdata['total_oz']:,.0f} oz")


if __name__ == '__main__':
    main()
