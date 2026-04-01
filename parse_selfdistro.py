#!/usr/bin/env python3
"""
Parse QBO Wholesale Unit Count Report for Flight Deck Brewing self-distribution.

Reads the CSV export, maps QBO SKU names → brand keys, excludes "Distro" rows
(Nappi shipments), and outputs data/selfdistro_data.json with monthly granularity.

CSV structure:
  - Two sections: "Wholesale Cans" and "Wholesale Kegs"
  - Each section has sub-sections headed by SKU name
  - Transaction rows: ,Customer,Date,Type,Full Name,Qty,Amount,Balance
  - Total rows: "Total for SKU_NAME,,,,,qty,amount,"

Case equivalents for mixed-format aggregation:
  - 1 sixtel (1/6 BBL) = 5.16 case equivalents (CE)
  - 1 half barrel (1/2 BBL) = 15.5 CE
  - 1 case = 1 CE
"""

import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime


# Case equivalent conversions
CE_PER_SIXTH = 5.16
CE_PER_HALF = 15.5


def load_sku_config():
    base = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base, 'data', 'sku_config.json')
    with open(config_path) as f:
        return json.load(f)


def build_qbo_name_map(config):
    """Build QBO SKU name prefix → brand_key lookup."""
    name_map = {}
    for brand_key, brand in config.get('brands', {}).items():
        for name in brand.get('qbo_names', []):
            name_map[name.strip().upper()] = brand_key
    return name_map


def build_qbo_exclude_patterns(config):
    """Build exclusion patterns for QBO."""
    return [p.strip().upper() for p in config.get('exclude_qbo', [])]


def is_excluded_qbo(sku_name, exclude_patterns):
    upper = sku_name.strip().upper()
    for pat in exclude_patterns:
        if pat in upper:
            return True
    return False


def match_qbo_brand(sku_name, name_map, exclude_patterns):
    """Match a QBO SKU name to a brand key."""
    if is_excluded_qbo(sku_name, exclude_patterns):
        return None
    upper = sku_name.strip().upper()
    # Try each known name as a prefix match
    best_match = None
    best_len = 0
    for prefix, brand_key in name_map.items():
        if upper.startswith(prefix) and len(prefix) > best_len:
            best_match = brand_key
            best_len = len(prefix)
    return best_match


def detect_format(sku_name):
    """
    Detect package format from QBO SKU name.
    Returns ('case', pack_config) or ('keg', keg_size).
    """
    lower = sku_name.lower()
    if '1/6' in lower:
        return 'keg_sixth'
    if '1/2' in lower:
        return 'keg_half'
    if 'case' in lower or '/4' in lower or '/6' in lower:
        return 'case'
    return 'case'  # default


def parse_qbo_csv(csv_path, name_map, exclude_patterns):
    """
    Parse QBO Wholesale Unit Count Report.
    Returns dict: month → brand → {cases, kegs_sixth, kegs_half, total_ce, revenue}.
    """
    monthly = defaultdict(lambda: defaultdict(lambda: {
        'cases': 0.0, 'kegs_sixth': 0.0, 'kegs_half': 0.0,
        'total_ce': 0.0, 'revenue': 0.0,
    }))

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    lines = content.strip().split('\n')

    current_section = None  # "Wholesale Cans" or "Wholesale Kegs"
    current_sku = None
    current_brand = None
    current_format = None

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith('Wholesale Cans'):
            current_section = 'cans'
            current_sku = None
            continue
        if stripped.startswith('Wholesale Kegs'):
            current_section = 'kegs'
            current_sku = None
            continue

        # Skip header rows and empty lines
        if not current_section:
            continue
        if not stripped or stripped.startswith(',Customer') or stripped.startswith('Wholesale Unit'):
            continue
        if stripped.startswith('FLIGHT DECK BREWING'):
            continue

        # Detect SKU header (a line that doesn't start with comma and isn't a Total line)
        if not stripped.startswith(',') and not stripped.startswith('Total for'):
            # This is a SKU name header
            current_sku = stripped.rstrip(',').strip()
            current_brand = match_qbo_brand(current_sku, name_map, exclude_patterns)
            current_format = detect_format(current_sku)
            if current_brand is None and not is_excluded_qbo(current_sku, exclude_patterns):
                # Try to identify it
                pass  # Silently skip unmatched
            continue

        # Skip Total lines
        if stripped.startswith('Total for'):
            continue

        # Transaction row: ,Customer,Date,Type,Full Name,Qty,Amount,Balance
        if stripped.startswith(',') and current_brand:
            # Parse CSV fields
            reader = csv.reader(io.StringIO(stripped))
            try:
                fields = next(reader)
            except StopIteration:
                continue

            if len(fields) < 7:
                continue

            date_str = fields[2].strip()
            tx_type = fields[3].strip()
            try:
                qty = float(fields[5].strip() or 0)
            except (ValueError, IndexError):
                continue
            try:
                amount = float(fields[6].strip().replace(',', '').replace('"', '') or 0)
            except (ValueError, IndexError):
                amount = 0.0

            # Parse date (MM/DD/YYYY format)
            try:
                dt = datetime.strptime(date_str, '%m/%d/%Y')
            except ValueError:
                continue

            month_key = dt.strftime('%Y-%m')
            brand_data = monthly[month_key][current_brand]

            if current_format == 'keg_sixth':
                brand_data['kegs_sixth'] += qty
                brand_data['total_ce'] += qty * CE_PER_SIXTH
            elif current_format == 'keg_half':
                brand_data['kegs_half'] += qty
                brand_data['total_ce'] += qty * CE_PER_HALF
            else:  # case
                brand_data['cases'] += qty
                brand_data['total_ce'] += qty
            brand_data['revenue'] += amount

    return dict(monthly)


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    # Find QBO CSV
    candidates = [
        os.path.join(base, '..', '..', 'FD Payroll & Financial Analysis', 'QBO and Toast Reports',
                     'FLIGHT DECK BREWING_Wholesale Unit Count Report (no deposits) - by SKU.csv'),
        '/sessions/determined-blissful-johnson/mnt/FD Payroll & Financial Analysis/QBO and Toast Reports/'
        'FLIGHT DECK BREWING_Wholesale Unit Count Report (no deposits) - by SKU.csv',
    ]
    csv_path = None
    for c in candidates:
        if os.path.isfile(c):
            csv_path = c
            break

    if csv_path is None:
        print("ERROR: QBO CSV not found")
        sys.exit(1)

    print(f"QBO CSV: {csv_path}")

    config = load_sku_config()
    name_map = build_qbo_name_map(config)
    exclude_patterns = build_qbo_exclude_patterns(config)
    print(f"Loaded {len(name_map)} QBO name mappings, {len(exclude_patterns)} exclusion patterns")

    monthly = parse_qbo_csv(csv_path, name_map, exclude_patterns)

    # Round values
    for month_key, brands in monthly.items():
        for brand_key, data in brands.items():
            data['cases'] = round(data['cases'], 2)
            data['kegs_sixth'] = round(data['kegs_sixth'], 2)
            data['kegs_half'] = round(data['kegs_half'], 2)
            data['total_ce'] = round(data['total_ce'], 2)
            data['revenue'] = round(data['revenue'], 2)

    # Build output
    output = {
        'generated': datetime.now().strftime('%Y-%m-%d'),
        'months': {},
    }

    for month_key in sorted(monthly.keys()):
        brands = monthly[month_key]
        total_ce = sum(d['total_ce'] for d in brands.values())
        total_revenue = sum(d['revenue'] for d in brands.values())
        output['months'][month_key] = {
            'total_ce': round(total_ce, 2),
            'total_revenue': round(total_revenue, 2),
            'brands': dict(brands),
        }

    # Write output
    out_path = os.path.join(base, 'data', 'selfdistro_data.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {os.path.getsize(out_path) / 1024:.1f} KB to {out_path}")

    # Summary
    print(f"\n=== SELF-DISTRO MONTHLY SUMMARY ===")
    for m in sorted(output['months'].keys()):
        data = output['months'][m]
        n_brands = len(data['brands'])
        print(f"  {m}: {data['total_ce']:7.1f} CE, ${data['total_revenue']:10,.2f}, {n_brands} brands")

    # Latest month breakdown
    sorted_months = sorted(output['months'].keys())
    if sorted_months:
        latest = sorted_months[-1]
        print(f"\n=== LATEST MONTH ({latest}) BRAND BREAKDOWN ===")
        brands_sorted = sorted(
            output['months'][latest]['brands'].items(),
            key=lambda x: x[1]['total_ce'],
            reverse=True
        )
        for bk, bdata in brands_sorted:
            print(f"  {bk:30s}  {bdata['cases']:6.1f} cs  {bdata['kegs_sixth']:5.1f} 6th  {bdata['kegs_half']:5.1f} half  {bdata['total_ce']:7.1f} CE  ${bdata['revenue']:,.2f}")


if __name__ == '__main__':
    main()
