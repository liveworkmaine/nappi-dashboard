#!/usr/bin/env python3
"""
update_all.py — One-click refresh for Flight Deck Brewing dashboards.

Runs the full data pipeline:
  1. Fetch latest inventory from Google Sheets (via fetch_inventory.py)
  2. Parse any new Nappi PDF reports (via parse_nappi.py)
  3. Parse Toast data (via parse_toast.py)
  4. Parse self-distribution data (via parse_selfdistro.py)
  5. Rebuild dashboard data (via build_dashboard_data.py)
  6. Update dashboard.html and production-planner.html
  7. Log forecast snapshot to data/forecast_log.json

Usage:
  python3 update_all.py           # Full refresh
  python3 update_all.py --skip-fetch  # Skip data fetching, just rebuild
  python3 update_all.py --dry-run     # Show what would happen without doing it
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def log(msg, level='info'):
    """Print timestamped log message."""
    ts = datetime.now().strftime('%H:%M:%S')
    icons = {'info': '→', 'ok': '✓', 'warn': '⚠', 'err': '✗', 'skip': '○'}
    icon = icons.get(level, '→')
    print(f"  {icon} [{ts}] {msg}")

def run_step(name, cmd, dry_run=False):
    """Run a pipeline step, return success boolean."""
    log(f"{name}...")
    if dry_run:
        log(f"  Would run: {' '.join(cmd)}", 'skip')
        return True
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR, timeout=120)
        if result.returncode == 0:
            # Print last few lines of output
            lines = result.stdout.strip().split('\n')
            for line in lines[-3:]:
                if line.strip():
                    log(f"  {line.strip()}", 'ok')
            return True
        else:
            log(f"  FAILED (exit {result.returncode})", 'err')
            if result.stderr:
                for line in result.stderr.strip().split('\n')[-3:]:
                    log(f"  {line.strip()}", 'err')
            return False
    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT after 120s", 'err')
        return False
    except FileNotFoundError:
        log(f"  Script not found: {cmd[0]}", 'err')
        return False

def check_data_freshness():
    """Check when each data source was last updated."""
    freshness = {}

    # Nappi data
    nappi_path = os.path.join(DATA_DIR, 'nappi_data.json')
    if os.path.exists(nappi_path):
        with open(nappi_path) as f:
            data = json.load(f)
            dates = sorted(data.keys())
            freshness['nappi'] = dates[-1] if dates else 'N/A'
    else:
        freshness['nappi'] = 'missing'

    # Brewery inventory
    inv_path = os.path.join(DATA_DIR, 'brewery_inventory.json')
    if os.path.exists(inv_path):
        with open(inv_path) as f:
            freshness['inventory'] = json.load(f).get('last_updated', 'N/A')
    else:
        freshness['inventory'] = 'missing'

    # Toast
    toast_path = os.path.join(DATA_DIR, 'toast_data.json')
    if os.path.exists(toast_path):
        with open(toast_path) as f:
            freshness['toast'] = json.load(f).get('generated', 'N/A')
    else:
        freshness['toast'] = 'missing'

    # Self-distro
    sd_path = os.path.join(DATA_DIR, 'selfdistro_data.json')
    if os.path.exists(sd_path):
        with open(sd_path) as f:
            freshness['selfdistro'] = json.load(f).get('generated', 'N/A')
    else:
        freshness['selfdistro'] = 'missing'

    return freshness

def log_forecast_snapshot():
    """Save a forecast snapshot to data/forecast_log.json."""
    log_path = os.path.join(DATA_DIR, 'forecast_log.json')

    # Load existing log
    if os.path.exists(log_path):
        with open(log_path) as f:
            forecast_log = json.load(f)
    else:
        forecast_log = []

    # Load current dashboard data for the snapshot
    dd_path = os.path.join(DATA_DIR, 'dashboard_data.json')
    if not os.path.exists(dd_path):
        log("No dashboard_data.json to snapshot", 'warn')
        return

    with open(dd_path) as f:
        dd = json.load(f)

    # Build snapshot
    freshness = check_data_freshness()

    # Extract brew queue summary
    brew_queue = dd.get('production', {}).get('brew_queue', [])
    tasting_room = dd.get('production', {}).get('tasting_room_only', [])

    brands_needing_brew = []
    for item in brew_queue:
        if item.get('brew_status') in ('BREW_NOW', 'PLAN'):
            brands_needing_brew.append({
                'name': item['name'],
                'status': item['brew_status'],
                'brew_by': item.get('brew_by'),
                'days_to_zero': item.get('days_to_zero'),
            })
    for item in tasting_room:
        if item.get('brew_status') in ('BREW_NOW', 'PLAN'):
            brands_needing_brew.append({
                'name': item['name'],
                'status': item['brew_status'],
                'brew_by': item.get('brew_by'),
                'days_to_zero': item.get('days_to_zero'),
            })

    snapshot = {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_freshness': freshness,
        'brands_needing_brew': len(brands_needing_brew),
        'brew_now_count': sum(1 for b in brands_needing_brew if b['status'] == 'BREW_NOW'),
        'plan_count': sum(1 for b in brands_needing_brew if b['status'] == 'PLAN'),
        'brew_details': brands_needing_brew,
        'avg_days_to_stockout': round(
            sum(item.get('days_to_zero', 999) for item in brew_queue if item.get('days_to_zero', 999) < 999) /
            max(1, sum(1 for item in brew_queue if item.get('days_to_zero', 999) < 999)),
            1
        ) if brew_queue else None,
    }

    # Append and keep last 90 days
    forecast_log.append(snapshot)
    cutoff = datetime.now().strftime('%Y-%m-%d')
    # Keep max 90 entries
    if len(forecast_log) > 90:
        forecast_log = forecast_log[-90:]

    with open(log_path, 'w') as f:
        json.dump(forecast_log, f, indent=2)

    log(f"Forecast snapshot saved ({len(brands_needing_brew)} brands need brewing)", 'ok')

def main():
    parser = argparse.ArgumentParser(description='Flight Deck Brewing — Full Dashboard Refresh')
    parser.add_argument('--skip-fetch', action='store_true', help='Skip data fetching, just rebuild')
    parser.add_argument('--dry-run', action='store_true', help='Show what would happen')
    args = parser.parse_args()

    print()
    print("  ╔════════════════════════════════════════════╗")
    print("  ║  FLIGHT DECK BREWING — Dashboard Refresh   ║")
    print("  ╚════════════════════════════════════════════╝")
    print()

    # Check data freshness before
    freshness = check_data_freshness()
    log(f"Current data: Nappi={freshness.get('nappi','?')} | Inv={freshness.get('inventory','?')} | Toast={freshness.get('toast','?')} | SD={freshness.get('selfdistro','?')}")
    print()

    steps_ok = 0
    steps_fail = 0
    steps_skip = 0

    # Step 1: Fetch inventory
    if not args.skip_fetch:
        # Note: fetch_inventory.py in Cowork mode reads from inventory_raw.json
        # which must be pre-fetched via Google Sheets MCP
        if os.path.exists(os.path.join(DATA_DIR, 'inventory_raw.json')):
            ok = run_step("Parsing brewery inventory",
                         [sys.executable, os.path.join(BASE_DIR, 'fetch_inventory.py')],
                         args.dry_run)
            steps_ok += ok; steps_fail += (not ok)
        else:
            log("inventory_raw.json not found — fetch via Cowork/MCP first", 'skip')
            steps_skip += 1
    else:
        log("Skipping inventory fetch", 'skip')
        steps_skip += 1

    # Step 2: Parse Nappi reports
    if not args.skip_fetch:
        pdfs_dir = os.path.join(BASE_DIR, 'pdfs')
        if os.path.exists(pdfs_dir) and any(f.endswith('.pdf') for f in os.listdir(pdfs_dir)):
            ok = run_step("Parsing Nappi PDF reports",
                         [sys.executable, os.path.join(BASE_DIR, 'parse_nappi.py')],
                         args.dry_run)
            steps_ok += ok; steps_fail += (not ok)
        else:
            log("No Nappi PDFs to parse", 'skip')
            steps_skip += 1
    else:
        log("Skipping Nappi parse", 'skip')
        steps_skip += 1

    # Step 3: Parse Toast data
    if not args.skip_fetch:
        toast_dir = os.path.join(BASE_DIR, 'toast-exports')
        if os.path.exists(toast_dir):
            ok = run_step("Parsing Toast POS data",
                         [sys.executable, os.path.join(BASE_DIR, 'parse_toast.py')],
                         args.dry_run)
            steps_ok += ok; steps_fail += (not ok)
        else:
            log("No toast-exports directory found", 'skip')
            steps_skip += 1
    else:
        log("Skipping Toast parse", 'skip')
        steps_skip += 1

    # Step 4: Parse self-distribution data
    if not args.skip_fetch:
        qbo_dir = os.path.join(BASE_DIR, 'qbo-exports')
        if os.path.exists(qbo_dir):
            ok = run_step("Parsing self-distribution data",
                         [sys.executable, os.path.join(BASE_DIR, 'parse_selfdistro.py')],
                         args.dry_run)
            steps_ok += ok; steps_fail += (not ok)
        else:
            log("No qbo-exports directory found", 'skip')
            steps_skip += 1
    else:
        log("Skipping self-distro parse", 'skip')
        steps_skip += 1

    # Step 5: Rebuild dashboard data
    log("Rebuilding dashboard data...")
    ok = run_step("Building dashboard data",
                 [sys.executable, os.path.join(BASE_DIR, 'build_dashboard_data.py')],
                 args.dry_run)
    steps_ok += ok; steps_fail += (not ok)

    # Step 6: Log forecast snapshot
    if not args.dry_run:
        log_forecast_snapshot()
    else:
        log("Would save forecast snapshot", 'skip')

    # Summary
    print()
    freshness_after = check_data_freshness()
    log(f"Updated data: Nappi={freshness_after.get('nappi','?')} | Inv={freshness_after.get('inventory','?')} | Toast={freshness_after.get('toast','?')} | SD={freshness_after.get('selfdistro','?')}")
    print()
    print(f"  Done: {steps_ok} succeeded, {steps_fail} failed, {steps_skip} skipped")

    if steps_fail > 0:
        print("  ⚠ Some steps failed — check output above")
        sys.exit(1)
    else:
        print("  ✓ All dashboards updated — open dashboard.html or production-planner.html")
    print()

if __name__ == '__main__':
    main()
