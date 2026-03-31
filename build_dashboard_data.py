#!/usr/bin/env python3
"""
Build compact dashboard data from the full nappi_data.json store.
Outputs dashboard_data.json with metrics for:
  - Trend (daily totals)
  - Products (per-SKU trends)
  - Accounts (new, reorder watch, upsell, order log)
  - Reps (scorecard with trends)
  - Production (alerts, velocity, stockout, format mix)
"""

import json
import os
import re
from collections import defaultdict


def load_sku_config(base_path=None):
    """Load per-SKU config (lead times, batch sizes) from sku_config.json."""
    if base_path is None:
        base_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_path, 'data', 'sku_config.json')
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


DEFAULT_LEAD_TIME_DAYS = 21
DEFAULT_BATCH_SIZE_BBL = 7


def get_sku_lead_time(sku_config, sku_code):
    """Get lead time for a SKU, falling back to default."""
    cfg = sku_config.get(str(sku_code), {})
    return cfg.get('lead_time_days', DEFAULT_LEAD_TIME_DAYS)


def get_sku_batch_size(sku_config, sku_code):
    """Get batch size for a SKU, falling back to default."""
    cfg = sku_config.get(str(sku_code), {})
    return cfg.get('batch_size_bbl', DEFAULT_BATCH_SIZE_BBL)


def build_dashboard_data(data, sku_config=None):
    """Build compact dashboard data dict from full nappi_data.json dict."""
    if sku_config is None:
        sku_config = {}
    dates = sorted(data.keys())
    latest_date = dates[-1]
    latest = data[latest_date]

    dashboard = {
        "dates": dates,
        "latest_date": latest_date,
        "trend": [],
        "products": {},
        "accounts": {
            "new_by_date": [], "reorder_watch": [], "upsell": [],
            "order_log": [], "total": 0, "on_premise": 0, "off_premise": 0,
        },
        "reps": {},
        "production": {
            "alerts": [], "velocity": [], "format_mix": {},
            "stockout_projections": [],
        },
        "totals": latest['sales_comp']['totals'],
    }

    # ── TREND ──
    for d in dates:
        snap = data[d]
        prods = snap['sales_comp']['products']
        accts = snap['accounts']
        cases_mtd = sum(p.get('actual_mtd', 0) for p in prods if 'BBL' not in p.get('format', ''))
        kegs_mtd = sum(p.get('actual_mtd', 0) for p in prods if 'BBL' in p.get('format', ''))
        cases_oh = sum(p.get('actual_on_hand', 0) for p in prods if 'BBL' not in p.get('format', ''))
        kegs_oh = sum(p.get('actual_on_hand', 0) for p in prods if 'BBL' in p.get('format', ''))
        dashboard["trend"].append({
            "d": d,
            "mtd": sum(p['mtd_sales'] for p in prods),
            "oh": sum(p['on_hand'] for p in prods),
            "cases_mtd": cases_mtd, "kegs_mtd": kegs_mtd,
            "cases_oh": cases_oh, "kegs_oh": kegs_oh,
            "accts": accts['total_accounts'],
            "active": accts['accounts_ordering_today'],
        })

    # ── PRODUCT TRENDS ──
    for d in dates:
        for p in data[d]['sales_comp']['products']:
            sku = p['sku_code']
            if sku not in dashboard["products"]:
                dashboard["products"][sku] = {
                    "name": p['product_name'], "format": p['format'],
                    "ce_factor": p['ce_factor'], "trend": []
                }
            dashboard["products"][sku]["trend"].append({
                "d": d, "mtd": p['mtd_sales'], "oh": p['on_hand'],
                "status": p['inventory_status'], "days": p['days_of_inventory'],
                "rate": p['daily_sell_rate'], "a_mtd": p['actual_mtd'],
                "a_oh": p['actual_on_hand'], "a_unit": p['actual_unit'],
            })

    # ── ACCOUNT TRACKING ──
    all_acct_info = {}
    prev_acct_mtd = {}
    seen_accounts = set()
    account_orders = defaultdict(list)

    for d in dates:
        detail = data[d]['accounts'].get('detail', [])
        current_ids = set()
        curr_mtd = {}

        for a in detail:
            acct = a['acct_num']
            sku = a['nappi_code']
            current_ids.add(acct)
            key = (acct, sku)
            curr_mtd[key] = a['mtd_qty']

            if acct not in all_acct_info:
                all_acct_info[acct] = {
                    "name": a['name'], "city": a['city'],
                    "address": a.get('address', ''),
                    "phone": a.get('phone', ''),
                    "type": a['premise_type'], "salesman": a['salesman'],
                    "first_seen": d, "skus": set(), "last_order": d,
                    "order_dates": set(), "total_mtd": 0,
                }
            all_acct_info[acct]["skus"].add(sku)
            all_acct_info[acct]["total_mtd"] = a['mtd_qty']

            prev = prev_acct_mtd.get(key, 0)
            if a['mtd_qty'] > prev:
                qty = a['mtd_qty'] - prev
                all_acct_info[acct]["last_order"] = d
                all_acct_info[acct]["order_dates"].add(d)
                account_orders[acct].append({
                    "d": d, "sku": sku, "qty": qty, "product": a['product_raw'],
                })

        if seen_accounts:
            new_this_date = current_ids - seen_accounts
            if new_this_date:
                new_accts = []
                for ac in new_this_date:
                    info = all_acct_info[ac]
                    products = [a['product_raw'] for a in detail if a['acct_num'] == ac]
                    new_accts.append({
                        "id": ac, "name": info['name'], "city": info['city'],
                        "type": info['type'], "rep": info['salesman'],
                        "products": products,
                    })
                dashboard["accounts"]["new_by_date"].append({
                    "d": d, "count": len(new_this_date), "accounts": new_accts
                })

        seen_accounts |= current_ids
        prev_acct_mtd = curr_mtd

    # Account counts
    on_p = sum(1 for a in all_acct_info.values() if a['type'] == 'on_premise')
    off_p = sum(1 for a in all_acct_info.values() if a['type'] != 'on_premise')
    dashboard["accounts"]["total"] = len(all_acct_info)
    dashboard["accounts"]["on_premise"] = on_p
    dashboard["accounts"]["off_premise"] = off_p

    # Reorder watch (5+ report-days since last order)
    reorder_threshold = 5
    for acct, info in sorted(all_acct_info.items(), key=lambda x: x[1]['last_order']):
        last_idx = dates.index(info['last_order']) if info['last_order'] in dates else 0
        days_since = len(dates) - 1 - last_idx
        if days_since >= reorder_threshold:
            dashboard["accounts"]["reorder_watch"].append({
                "id": acct, "name": info['name'], "city": info['city'],
                "type": info['type'], "rep": info['salesman'],
                "last_order": info['last_order'], "days_since": days_since,
                "products": len(info['skus']), "mtd": info['total_mtd'],
            })
    dashboard["accounts"]["reorder_watch"].sort(key=lambda x: -x['days_since'])

    # Upsell (1-2 products)
    sku_names = {s: f"{p['name']} {p['format']}" for s, p in dashboard["products"].items()}
    sku_popularity = defaultdict(int)
    for info in all_acct_info.values():
        for s in info['skus']:
            sku_popularity[s] += 1
    popular_skus = sorted(sku_popularity.keys(), key=lambda s: sku_popularity[s], reverse=True)

    for acct, info in sorted(all_acct_info.items(), key=lambda x: len(x[1]['skus'])):
        n_skus = len(info['skus'])
        if n_skus <= 2:
            suggestions = []
            for s in popular_skus:
                if s not in info['skus'] and len(suggestions) < 2:
                    sku_info = dashboard["products"].get(s, {})
                    is_keg = 'BBL' in sku_info.get('format', '')
                    is_on = info['type'] == 'on_premise'
                    if (is_on and is_keg) or (not is_on and not is_keg):
                        suggestions.append(sku_names.get(s, s))
            dashboard["accounts"]["upsell"].append({
                "id": acct, "name": info['name'], "city": info['city'],
                "type": info['type'], "rep": info['salesman'],
                "current": [sku_names.get(s, s) for s in info['skus']],
                "suggest": suggestions, "n_products": n_skus,
            })
    dashboard["accounts"]["upsell"].sort(key=lambda x: x['n_products'])

    # Full account roster with days-since-last-order
    roster = []
    for acct, info in all_acct_info.items():
        last_idx = dates.index(info['last_order']) if info['last_order'] in dates else 0
        days_since = len(dates) - 1 - last_idx
        n_orders = len(info.get('order_dates', set()))
        roster.append({
            "id": acct, "name": info['name'], "city": info['city'],
            "address": info.get('address', ''),
            "phone": info.get('phone', ''),
            "type": info['type'], "rep": info['salesman'],
            "first_seen": info['first_seen'], "last_order": info['last_order'],
            "days_quiet": days_since, "n_products": len(info['skus']),
            "products": sorted([sku_names.get(s, s) for s in info['skus']]),
            "n_orders": n_orders, "mtd": info['total_mtd'],
        })
    roster.sort(key=lambda x: -x['days_quiet'])
    dashboard["accounts"]["roster"] = roster

    # Recent order log
    all_order_entries = []
    for acct, orders in account_orders.items():
        info = all_acct_info[acct]
        for d in sorted(set(o['d'] for o in orders), reverse=True):
            day_orders = [o for o in orders if o['d'] == d]
            all_order_entries.append({
                "d": d, "name": info['name'], "city": info['city'],
                "rep": info['salesman'], "type": info['type'],
                "items": [{"product": o['product'], "qty": o['qty']} for o in day_orders],
            })
    all_order_entries.sort(key=lambda x: x['d'], reverse=True)
    dashboard["accounts"]["order_log"] = all_order_entries[:30]

    # ── REP SCORECARD ──
    rep_data = defaultdict(lambda: {"dates": {}, "new_accounts": 0})
    for d in dates:
        sm = data[d]['accounts'].get('salesman_summary', {})
        for name, stats in sm.items():
            rep_data[name]["dates"][d] = {
                "mtd": stats.get('mtd_cases', 0),
                "accts": stats.get('account_count', 0),
                "daily": stats.get('daily_cases', 0),
            }
    for item in dashboard["accounts"]["new_by_date"]:
        for a in item["accounts"]:
            rep_data[a["rep"]]["new_accounts"] += 1

    for name, rd in rep_data.items():
        vals = [rd["dates"].get(d, {}).get("mtd", 0) for d in dates]
        latest_val = vals[-1] if vals else 0
        if len(vals) >= 4:
            early_rate = (vals[2] - vals[0]) / 2
            recent_rate = (vals[-1] - vals[-3]) / 2
            trend = "up" if recent_rate > early_rate * 1.3 else "down" if recent_rate < early_rate * 0.7 else "steady"
        else:
            trend = "steady"
        latest_sm = data[latest_date]['accounts'].get('salesman_summary', {}).get(name, {})
        dashboard["reps"][name] = {
            "mtd": latest_val,
            "accts": latest_sm.get('account_count', 0),
            "daily": latest_sm.get('daily_cases', 0),
            "new_accts": rd["new_accounts"],
            "trend": trend,
            "history": vals,
        }

    # ── PRODUCTION ──
    from datetime import datetime, timedelta

    for p in latest['sales_comp']['products']:
        sku = p['sku_code']
        lead_time = get_sku_lead_time(sku_config, sku)
        batch_size = get_sku_batch_size(sku_config, sku)
        first_prods = data[dates[0]]['sales_comp']['products']
        first_p = [x for x in first_prods if x['sku_code'] == sku]
        early_rate = first_p[0]['daily_sell_rate'] if first_p else 0
        current_rate = p['daily_sell_rate']
        velocity_pct = ((current_rate - early_rate) / early_rate * 100) if early_rate > 0 else 0
        a_rate = p.get('actual_daily_rate', 0)
        a_oh = p['actual_on_hand']
        days_to_zero = a_oh / a_rate if a_rate > 0 else 999
        brew_urgency = days_to_zero - lead_time
        # Projected stockout and brew-by dates
        latest_dt = datetime.strptime(latest_date, '%Y-%m-%d')
        stockout_dt = latest_dt + timedelta(days=days_to_zero)
        brew_by_dt = stockout_dt - timedelta(days=lead_time)
        brew_status = "BREW_NOW" if brew_urgency <= 0 else "PLAN" if brew_urgency <= 7 else "OK"
        # How many units needed to reach lead-time safety stock
        target_oh = round(a_rate * lead_time)
        shortfall = max(0, target_oh - a_oh)

        entry = {
            "sku": sku, "name": p['product_name'], "format": p['format'],
            "status": p['inventory_status'], "days_inv": p['days_of_inventory'],
            "on_hand": p['on_hand'], "a_oh": a_oh,
            "rate": current_rate, "a_rate": a_rate,
            "a_unit": p['actual_unit'],
            "velocity_pct": round(velocity_pct),
            "days_to_zero": round(days_to_zero, 1),
            "is_keg": 'BBL' in p.get('format', ''),
            "brew_status": brew_status,
            "brew_urgency": round(brew_urgency, 1),
            "brew_by": brew_by_dt.strftime('%Y-%m-%d'),
            "stockout_date": stockout_dt.strftime('%Y-%m-%d'),
            "target_oh": target_oh,
            "shortfall": shortfall,
            "lead_time": lead_time,
            "batch_size": batch_size,
        }
        if p['inventory_status'] in ('CRITICAL', 'ORDER_NOW'):
            dashboard["production"]["alerts"].append(entry)
        dashboard["production"]["velocity"].append(entry)
        dashboard["production"]["stockout_projections"].append(entry)

    dashboard["production"]["alerts"].sort(key=lambda x: x['days_inv'])

    # Brew queue: sorted by urgency (most urgent first)
    dashboard["production"]["brew_queue"] = sorted(
        dashboard["production"]["stockout_projections"],
        key=lambda x: x['brew_urgency']
    )

    # Restock events: detect when on_hand increased between consecutive dates
    restocks = []
    for i in range(1, len(dates)):
        prev_prods = {p['sku_code']: p for p in data[dates[i-1]]['sales_comp']['products']}
        curr_prods = {p['sku_code']: p for p in data[dates[i]]['sales_comp']['products']}
        for sku_code, cp in curr_prods.items():
            if sku_code in prev_prods:
                prev_oh = prev_prods[sku_code].get('actual_on_hand', 0)
                curr_oh = cp.get('actual_on_hand', 0)
                if curr_oh > prev_oh:
                    restocks.append({
                        "d": dates[i], "sku": sku_code,
                        "name": cp['product_name'], "format": cp['format'],
                        "added": curr_oh - prev_oh, "a_unit": cp.get('actual_unit', ''),
                        "prev_oh": prev_oh, "new_oh": curr_oh,
                    })
    restocks.sort(key=lambda x: x['d'], reverse=True)
    dashboard["production"]["restocks"] = restocks
    dashboard["production"]["stockout_projections"].sort(key=lambda x: x['days_to_zero'])

    can_prods = [p for p in latest['sales_comp']['products'] if 'BBL' not in p.get('format', '')]
    keg_prods = [p for p in latest['sales_comp']['products'] if 'BBL' in p.get('format', '')]
    dashboard["production"]["format_mix"] = {
        "can_mtd": sum(p['mtd_sales'] for p in can_prods),
        "keg_mtd": sum(p['mtd_sales'] for p in keg_prods),
        "can_oh": sum(p['on_hand'] for p in can_prods),
        "keg_oh": sum(p['on_hand'] for p in keg_prods),
        "a_can_mtd": sum(p.get('actual_mtd', 0) for p in can_prods),
        "a_keg_mtd": sum(p.get('actual_mtd', 0) for p in keg_prods),
        "a_can_oh": sum(p.get('actual_on_hand', 0) for p in can_prods),
        "a_keg_oh": sum(p.get('actual_on_hand', 0) for p in keg_prods),
    }

    # ── SKU CONFIG (for dashboard display) ──
    dashboard["sku_config"] = sku_config

    # ── PRODUCT PENETRATION (accounts per SKU over time) ──
    product_penetration = {}
    for d in dates:
        dist = data[d]['accounts'].get('product_distribution', {})
        for sku_code, count in dist.items():
            if sku_code not in product_penetration:
                product_penetration[sku_code] = []
            product_penetration[sku_code].append({"d": d, "accounts": count})
    dashboard["product_penetration"] = product_penetration

    # ── ORDERING TODAY (from latest report) ──
    dashboard["ordering_today"] = latest['accounts'].get('accounts_ordering_today', 0)

    # Clean sets for JSON
    def clean(obj):
        if isinstance(obj, set): return sorted(list(obj))
        if isinstance(obj, dict): return {k: clean(v) for k, v in obj.items()}
        if isinstance(obj, list): return [clean(i) for i in obj]
        return obj

    return clean(dashboard)


def update_dashboard_html(dashboard_data, html_path):
    """Replace the DATA constant in dashboard.html with new data."""
    compact = json.dumps(dashboard_data, separators=(',', ':'))

    with open(html_path) as f:
        html = f.read()

    html = re.sub(r'const D = \{.*?\};', f'const D = {compact};', html, count=1, flags=re.DOTALL)

    with open(html_path, 'w') as f:
        f.write(html)

    return len(html)


if __name__ == '__main__':
    base = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(base, 'data', 'nappi_data.json')) as f:
        data = json.load(f)

    sku_config = load_sku_config(base)
    if sku_config:
        print(f"Loaded SKU config: {len(sku_config)} SKUs")
    else:
        print("No sku_config.json found, using defaults")

    dashboard = build_dashboard_data(data, sku_config)

    compact = json.dumps(dashboard, separators=(',', ':'))
    with open(os.path.join(base, 'data', 'dashboard_data.json'), 'w') as f:
        f.write(compact)
    print(f"Dashboard data: {len(compact)/1024:.1f} KB")

    size = update_dashboard_html(dashboard, os.path.join(base, 'dashboard.html'))
    print(f"Dashboard HTML updated: {size/1024:.1f} KB")
