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
from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timedelta


SIXTEL_OZ = 661.0


def load_sku_config(base_path=None):
    """Load brand-centric sku_config.json and build reverse lookups."""
    if base_path is None:
        base_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_path, 'data', 'sku_config.json')
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def load_brewery_inventory(base_path=None):
    """Load brewery_inventory.json if it exists."""
    if base_path is None:
        base_path = os.path.dirname(os.path.abspath(__file__))
    inv_path = os.path.join(base_path, 'data', 'brewery_inventory.json')
    if os.path.exists(inv_path):
        with open(inv_path) as f:
            return json.load(f)
    return None


def load_toast_data(base_path=None):
    """Load toast_data.json if it exists."""
    if base_path is None:
        base_path = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_path, 'data', 'toast_data.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def load_selfdistro_data(base_path=None):
    """Load selfdistro_data.json if it exists."""
    if base_path is None:
        base_path = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_path, 'data', 'selfdistro_data.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def get_current_month_key():
    """Get YYYY-MM for current month."""
    return datetime.now().strftime('%Y-%m')


def get_toast_velocity_for_brand(toast_data, brand_key, month_key=None):
    """
    Get Toast velocity for a brand for a specific month.
    Returns dict with daily_kegs, daily_oz, qty_sold, or zeros.
    """
    zero = {'daily_kegs': 0.0, 'daily_oz': 0.0, 'qty_sold': 0, 'total_oz': 0.0, 'pour_breakdown': {}}
    if not toast_data:
        return zero

    # Use trailing_30d (most recent month) if no month specified
    if month_key is None:
        t30 = toast_data.get('brunswick', {}).get('trailing_30d')
        if not t30:
            return zero
        brand = t30.get('brands', {}).get(brand_key)
        if not brand:
            return zero
        return {
            'daily_kegs': brand.get('daily_kegs_equiv', 0),
            'daily_oz': brand.get('daily_oz', 0),
            'qty_sold': brand.get('qty_sold', 0),
            'total_oz': brand.get('total_oz', 0),
            'pour_breakdown': brand.get('pour_breakdown', {}),
        }

    months = toast_data.get('brunswick', {}).get('months', {})
    month_data = months.get(month_key)
    if not month_data:
        return zero
    brand = month_data.get('brands', {}).get(brand_key)
    if not brand:
        return zero
    return {
        'daily_kegs': brand.get('daily_kegs_equiv', 0),
        'daily_oz': brand.get('daily_oz', 0),
        'qty_sold': brand.get('qty_sold', 0),
        'total_oz': brand.get('total_oz', 0),
        'pour_breakdown': brand.get('pour_breakdown', {}),
    }


def get_mmm_velocity_for_brand(toast_data, brand_key, month_key=None):
    """Get MMM velocity for a brand. Only has data Jun-Sep."""
    zero = {'daily_kegs': 0.0, 'qty_sold': 0, 'total_oz': 0.0}
    if not toast_data:
        return zero
    mmm_months = toast_data.get('mmm', {}).get('months', {})
    if month_key and month_key in mmm_months:
        brand = mmm_months[month_key].get('brands', {}).get(brand_key)
        if brand:
            return {
                'daily_kegs': brand.get('daily_kegs_equiv', 0),
                'qty_sold': brand.get('qty_sold', 0),
                'total_oz': brand.get('total_oz', 0),
            }
    return zero


def get_selfdistro_velocity_for_brand(sd_data, brand_key, month_key=None):
    """Get self-distro velocity for a brand for a specific month."""
    zero = {'daily_ce': 0.0, 'cases': 0.0, 'kegs_sixth': 0.0, 'kegs_half': 0.0, 'total_ce': 0.0}
    if not sd_data:
        return zero
    months = sd_data.get('months', {})

    # Find most recent month if none specified
    if month_key is None:
        sorted_m = sorted(months.keys())
        if not sorted_m:
            return zero
        month_key = sorted_m[-1]

    month_data = months.get(month_key)
    if not month_data:
        return zero
    brand = month_data.get('brands', {}).get(brand_key)
    if not brand:
        return zero

    # Calculate days in this month for daily rate
    try:
        year, month = int(month_key[:4]), int(month_key[5:7])
        _, days = monthrange(year, month)
    except (ValueError, IndexError):
        days = 30

    total_ce = brand.get('total_ce', 0)
    return {
        'daily_ce': round(total_ce / days, 3) if days > 0 else 0,
        'cases': brand.get('cases', 0),
        'kegs_sixth': brand.get('kegs_sixth', 0),
        'kegs_half': brand.get('kegs_half', 0),
        'total_ce': total_ce,
    }


def build_multichannel_velocity(sku_config, toast_data, sd_data, brewery_inv):
    """
    Build multi-channel velocity data for ALL brands (Nappi and non-Nappi).
    Returns dict of brand_key → velocity metrics.
    """
    brands = sku_config.get('brands', {})
    result = {}

    for brand_key, brand in brands.items():
        if not brand.get('active', True):
            continue  # skip retired brands

        toast_v = get_toast_velocity_for_brand(toast_data, brand_key)
        sd_v = get_selfdistro_velocity_for_brand(sd_data, brand_key)

        # Toast velocity in kegs/day
        toast_daily_kegs = toast_v.get('daily_kegs', 0)

        # Self-distro: convert daily CE to daily kegs (1 CE ≈ 1/5.16 sixtel)
        sd_daily_ce = sd_v.get('daily_ce', 0)
        sd_daily_kegs = sd_daily_ce / 5.16 if sd_daily_ce > 0 else 0

        # Total non-Nappi velocity in kegs/day
        total_daily_kegs = toast_daily_kegs + sd_daily_kegs

        # YoY comparison
        toast_same_ly = None
        if toast_data:
            smly = toast_data.get('brunswick', {}).get('same_month_last_year')
            if smly:
                ly_brand = smly.get('brands', {}).get(brand_key)
                if ly_brand:
                    toast_same_ly = ly_brand.get('daily_kegs_equiv', 0)

        # Monthly trend (last 6 months)
        monthly_trend = []
        if toast_data:
            all_months = sorted(toast_data.get('brunswick', {}).get('months', {}).keys())
            for m in all_months[-6:]:
                m_data = toast_data['brunswick']['months'][m].get('brands', {}).get(brand_key)
                if m_data:
                    monthly_trend.append({
                        'month': m,
                        'daily_kegs': m_data.get('daily_kegs_equiv', 0),
                        'qty_sold': m_data.get('qty_sold', 0),
                    })

        result[brand_key] = {
            'display_name': brand.get('display_name', brand_key),
            'toast_daily_kegs': round(toast_daily_kegs, 3),
            'toast_qty': toast_v.get('qty_sold', 0),
            'toast_pour_breakdown': toast_v.get('pour_breakdown', {}),
            'sd_daily_kegs': round(sd_daily_kegs, 3),
            'sd_daily_ce': round(sd_daily_ce, 3),
            'sd_cases': sd_v.get('cases', 0),
            'sd_kegs_sixth': sd_v.get('kegs_sixth', 0),
            'total_daily_kegs': round(total_daily_kegs, 3),
            'toast_same_month_ly': toast_same_ly,
            'monthly_trend': monthly_trend,
        }

    return result


DEFAULT_LEAD_TIME_DAYS = 21
DEFAULT_BATCH_SIZE_BBL = 7


def build_sku_to_brand(sku_config):
    """Build reverse lookup: Nappi SKU code → (brand_key, brand_config)."""
    sku_to_brand = {}
    brands = sku_config.get('brands', {})
    for brand_key, brand in brands.items():
        for sku_code, sku_info in brand.get('nappi_skus', {}).items():
            sku_to_brand[str(sku_code)] = (brand_key, brand)
    return sku_to_brand


def get_sku_lead_time(sku_config, sku_code):
    """Get lead time for a SKU, falling back to default."""
    # New brand-centric config
    sku_to_brand = build_sku_to_brand(sku_config)
    result = sku_to_brand.get(str(sku_code))
    if result:
        _, brand = result
        return brand.get('lead_time_days', DEFAULT_LEAD_TIME_DAYS)
    # Legacy flat config fallback
    cfg = sku_config.get(str(sku_code), {})
    return cfg.get('lead_time_days', DEFAULT_LEAD_TIME_DAYS)


def get_sku_batch_size(sku_config, sku_code):
    """Get batch size for a SKU, falling back to default."""
    # New brand-centric config
    sku_to_brand = build_sku_to_brand(sku_config)
    result = sku_to_brand.get(str(sku_code))
    if result:
        _, brand = result
        return brand.get('batch_size_bbl', DEFAULT_BATCH_SIZE_BBL)
    # Legacy flat config fallback
    cfg = sku_config.get(str(sku_code), {})
    return cfg.get('batch_size_bbl', DEFAULT_BATCH_SIZE_BBL)


def get_brewery_on_hand_for_sku(sku_code, sku_config, brewery_inv):
    """
    Look up brewery on-hand for a Nappi SKU.
    Maps SKU → brand → inventory, then picks the right unit column.
    Returns (brewery_on_hand, unit_type) or (0, None) if not found.
    """
    if not brewery_inv:
        return 0, None

    sku_to_brand = build_sku_to_brand(sku_config)
    result = sku_to_brand.get(str(sku_code))
    if not result:
        return 0, None

    brand_key, brand = result
    brand_inv = brewery_inv.get('brands', {}).get(brand_key)
    if not brand_inv:
        return 0, None

    sku_info = brand.get('nappi_skus', {}).get(str(sku_code), {})
    sku_type = sku_info.get('type', '')

    if sku_type == 'keg':
        # For keg SKUs, return sixth-barrel count (that's what Nappi distributes)
        return brand_inv.get('kegs_sixth', 0), 'kegs'
    elif sku_type == 'case':
        case_size = sku_info.get('case_size', '16oz')
        if case_size == '12oz':
            return brand_inv.get('cases_12oz', 0), 'cases'
        else:
            return brand_inv.get('cases_16oz', 0), 'cases'

    return 0, None


def build_dashboard_data(data, sku_config=None, brewery_inv=None,
                          toast_data=None, sd_data=None):
    """Build compact dashboard data dict from full nappi_data.json dict."""
    if sku_config is None:
        sku_config = {}
    if brewery_inv is None:
        brewery_inv = {}
    dates = sorted(data.keys())
    latest_date = dates[-1]
    latest = data[latest_date]

    # Build multi-channel velocity
    mc_velocity = build_multichannel_velocity(sku_config, toast_data, sd_data, brewery_inv)

    # Data freshness info
    data_freshness = {
        'nappi': latest_date,
        'inventory': brewery_inv.get('last_updated', 'N/A') if brewery_inv else 'N/A',
        'toast': toast_data.get('generated', 'N/A') if toast_data else 'N/A',
        'selfdistro': sd_data.get('generated', 'N/A') if sd_data else 'N/A',
    }
    # Get Toast latest month
    if toast_data:
        t30 = toast_data.get('brunswick', {}).get('trailing_30d', {})
        data_freshness['toast_month'] = t30.get('month', 'N/A')
    else:
        data_freshness['toast_month'] = 'N/A'
    # Get self-distro latest month
    if sd_data:
        sd_months = sorted(sd_data.get('months', {}).keys())
        data_freshness['selfdistro_month'] = sd_months[-1] if sd_months else 'N/A'
    else:
        data_freshness['selfdistro_month'] = 'N/A'

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
        "brewery_inventory": brewery_inv,
        "multichannel": mc_velocity,
        "data_freshness": data_freshness,
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

    # Cache sku_to_brand lookup (avoid rebuilding per SKU)
    _sku_to_brand_cache = build_sku_to_brand(sku_config)

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
        a_oh = p['actual_on_hand']  # Nappi on-hand

        # Brewery on-hand for this SKU's format
        brewery_oh, _ = get_brewery_on_hand_for_sku(sku, sku_config, brewery_inv)
        total_available = a_oh + brewery_oh

        # Use total_available for days-to-zero calculation
        days_to_zero = total_available / a_rate if a_rate > 0 else 999
        brew_urgency = days_to_zero - lead_time
        # Projected stockout and brew-by dates
        latest_dt = datetime.strptime(latest_date, '%Y-%m-%d')
        stockout_dt = latest_dt + timedelta(days=days_to_zero)
        brew_by_dt = stockout_dt - timedelta(days=lead_time)
        brew_status = "BREW_NOW" if brew_urgency <= 0 else "PLAN" if brew_urgency <= 7 else "OK"
        # How many units needed to reach lead-time safety stock
        target_oh = round(a_rate * lead_time)
        shortfall = max(0, target_oh - total_available)

        # Look up brand key for this SKU
        brand_result = _sku_to_brand_cache.get(str(sku))
        brand_key = brand_result[0] if brand_result else None

        # Multi-channel velocity for this brand
        mc = mc_velocity.get(brand_key, {}) if brand_key else {}
        toast_daily = mc.get('toast_daily_kegs', 0)
        sd_daily = mc.get('sd_daily_kegs', 0)
        nappi_daily_kegs = a_rate / 5.16 if 'BBL' not in p.get('format', '') else a_rate
        total_daily_all_channels = nappi_daily_kegs + toast_daily + sd_daily

        # Channel split percentages
        channel_split = {}
        if total_daily_all_channels > 0:
            channel_split = {
                'nappi_pct': round(nappi_daily_kegs / total_daily_all_channels * 100),
                'toast_pct': round(toast_daily / total_daily_all_channels * 100),
                'sd_pct': round(sd_daily / total_daily_all_channels * 100),
            }

        # YoY seasonality indicator
        toast_yoy = None
        if mc.get('toast_same_month_ly') is not None and mc.get('toast_same_month_ly', 0) > 0:
            toast_yoy = round((toast_daily / mc['toast_same_month_ly'] - 1) * 100)

        entry = {
            "sku": sku, "name": p['product_name'], "format": p['format'],
            "status": p['inventory_status'], "days_inv": p['days_of_inventory'],
            "on_hand": p['on_hand'], "a_oh": a_oh,
            "brewery_oh": brewery_oh,
            "total_available": total_available,
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
            "brand_key": brand_key,
            "channel": "nappi",
            "toast_daily_kegs": toast_daily,
            "sd_daily_kegs": sd_daily,
            "total_daily_all_channels": round(total_daily_all_channels, 3),
            "channel_split": channel_split,
            "toast_yoy_pct": toast_yoy,
        }
        if p['inventory_status'] in ('CRITICAL', 'ORDER_NOW'):
            dashboard["production"]["alerts"].append(entry)
        dashboard["production"]["velocity"].append(entry)
        dashboard["production"]["stockout_projections"].append(entry)

    # ── TASTING ROOM ONLY BRANDS (non-Nappi) — now with real Toast velocity ──
    tasting_room_only = []
    nappi_brand_keys = set()
    for sku_code, (bk, _) in _sku_to_brand_cache.items():
        nappi_brand_keys.add(bk)

    latest_dt = datetime.strptime(latest_date, '%Y-%m-%d')

    for brand_key, brand in sku_config.get('brands', {}).items():
        if brand_key in nappi_brand_keys:
            continue  # already covered by Nappi SKUs
        if not brand.get('active', True):
            continue  # skip retired brands
        brand_inv = brewery_inv.get('brands', {}).get(brand_key, {})
        mc = mc_velocity.get(brand_key, {})

        # Get inventory totals
        kegs_sixth = brand_inv.get('kegs_sixth', 0) if brand_inv else 0
        kegs_half = brand_inv.get('kegs_half', 0) if brand_inv else 0
        cases_16oz = brand_inv.get('cases_16oz', 0) if brand_inv else 0
        cases_12oz = brand_inv.get('cases_12oz', 0) if brand_inv else 0
        total_units = kegs_sixth + kegs_half + cases_16oz + cases_12oz

        # Get velocity from Toast + self-distro
        toast_daily_kegs = mc.get('toast_daily_kegs', 0)
        sd_daily_kegs = mc.get('sd_daily_kegs', 0)
        total_daily_kegs = toast_daily_kegs + sd_daily_kegs

        # Skip if no inventory AND no velocity
        if total_units == 0 and total_daily_kegs == 0:
            continue

        # Calculate days to zero based on total daily kegs consumed
        # Convert inventory to keg equivalents: 1 sixth = 1, 1 half = 3, cases ≈ 1/5.16
        inv_kegs_equiv = kegs_sixth + (kegs_half * 3) + ((cases_16oz + cases_12oz) / 5.16)
        days_to_zero = inv_kegs_equiv / total_daily_kegs if total_daily_kegs > 0 else 999
        lead_time = brand.get('lead_time_days', DEFAULT_LEAD_TIME_DAYS)
        batch_size = brand.get('batch_size_bbl', DEFAULT_BATCH_SIZE_BBL)
        brew_urgency = days_to_zero - lead_time
        brew_status = "BREW_NOW" if brew_urgency <= 0 else "PLAN" if brew_urgency <= 7 else "OK"
        stockout_dt = latest_dt + timedelta(days=days_to_zero)
        brew_by_dt = stockout_dt - timedelta(days=lead_time)

        # Channel split
        channel_split = {}
        if total_daily_kegs > 0:
            channel_split = {
                'nappi_pct': 0,
                'toast_pct': round(toast_daily_kegs / total_daily_kegs * 100),
                'sd_pct': round(sd_daily_kegs / total_daily_kegs * 100),
            }

        # YoY
        toast_yoy = None
        if mc.get('toast_same_month_ly') is not None and mc.get('toast_same_month_ly', 0) > 0:
            toast_yoy = round((toast_daily_kegs / mc['toast_same_month_ly'] - 1) * 100)

        entry = {
            "brand_key": brand_key,
            "name": brand.get('display_name', brand_key),
            "style": brand.get('style'),
            "kegs_sixth": kegs_sixth,
            "kegs_half": kegs_half,
            "cases_16oz": cases_16oz,
            "cases_12oz": cases_12oz,
            "inv_kegs_equiv": round(inv_kegs_equiv, 1),
            "lead_time": lead_time,
            "batch_size": batch_size,
            "channel": "tasting_room",
            "toast_daily_kegs": toast_daily_kegs,
            "sd_daily_kegs": sd_daily_kegs,
            "total_daily_kegs": round(total_daily_kegs, 3),
            "days_to_zero": round(days_to_zero, 1),
            "brew_urgency": round(brew_urgency, 1),
            "brew_status": brew_status,
            "brew_by": brew_by_dt.strftime('%Y-%m-%d'),
            "stockout_date": stockout_dt.strftime('%Y-%m-%d'),
            "channel_split": channel_split,
            "toast_yoy_pct": toast_yoy,
            "toast_qty": mc.get('toast_qty', 0),
            "monthly_trend": mc.get('monthly_trend', []),
        }
        tasting_room_only.append(entry)

    # Sort by brew urgency (most urgent first)
    tasting_room_only.sort(key=lambda x: x.get('brew_urgency', 999))
    dashboard["production"]["tasting_room_only"] = tasting_room_only

    # ── MMM DATA ──
    mmm_data = {}
    if toast_data:
        mmm_months = toast_data.get('mmm', {}).get('months', {})
        mmm_data = {
            'months': mmm_months,
            'has_data': len(mmm_months) > 0,
        }
    dashboard["mmm"] = mmm_data

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


def build_production_planner_data(dashboard, sku_config, brewery_inv, toast_data, sd_data):
    """
    Build the production planner dataset from the main dashboard data.
    This produces the data shape consumed by production-planner.html.
    """
    brands_cfg = sku_config.get('brands', {})
    mc = dashboard.get('multichannel', {})
    brew_queue = dashboard.get('production', {}).get('brew_queue', [])
    tasting_room = dashboard.get('production', {}).get('tasting_room_only', [])
    data_freshness = dashboard.get('data_freshness', {})
    latest_date = dashboard.get('latest_date', datetime.now().strftime('%Y-%m-%d'))
    latest_dt = datetime.strptime(latest_date, '%Y-%m-%d')
    current_month = latest_dt.strftime('%Y-%m')

    # Constants for unit conversions
    SIXTEL_PER_BBL = 6.0  # 1 barrel = ~6 sixtels
    HALF_PER_BBL = 2.0    # 1 barrel = 2 half-barrels
    CASES_16OZ_PER_BBL = 27.5  # ~27.5 4-packs of 16oz per barrel
    CASES_12OZ_PER_BBL = 41.3  # ~41.3 6-packs of 12oz per barrel

    production_plan = []
    seen_brand_keys = set()

    # ── Process Nappi brands (from brew_queue) ──
    # Group by brand_key to avoid duplicate entries per SKU
    brand_nappi_data = {}
    for item in brew_queue:
        bk = item.get('brand_key')
        if not bk:
            continue
        if bk not in brand_nappi_data:
            brand_nappi_data[bk] = {'cases': 0, 'kegs': 0, 'nappi_daily_cases': 0, 'nappi_daily_kegs': 0}
        if item.get('is_keg'):
            brand_nappi_data[bk]['kegs'] = item.get('a_oh', 0)
            brand_nappi_data[bk]['nappi_daily_kegs'] = item.get('a_rate', 0)
        else:
            brand_nappi_data[bk]['cases'] = item.get('a_oh', 0)
            brand_nappi_data[bk]['nappi_daily_cases'] = item.get('a_rate', 0)

    for brand_key, brand in brands_cfg.items():
        if not brand.get('active', True):
            continue
        seen_brand_keys.add(brand_key)

        # Inventory from brewery
        brand_inv = (brewery_inv or {}).get('brands', {}).get(brand_key, {})
        kegs_sixth = brand_inv.get('kegs_sixth', 0)
        kegs_half = brand_inv.get('kegs_half', 0)
        cases_16oz = brand_inv.get('cases_16oz', 0)
        cases_12oz = brand_inv.get('cases_12oz', 0)

        # Nappi on-hand
        nappi = brand_nappi_data.get(brand_key, {})
        nappi_cases = nappi.get('cases', 0)
        nappi_kegs = nappi.get('kegs', 0)

        # Convert everything to barrels
        inv_bbl = (
            kegs_sixth / SIXTEL_PER_BBL +
            kegs_half / HALF_PER_BBL +
            cases_16oz / CASES_16OZ_PER_BBL +
            cases_12oz / CASES_12OZ_PER_BBL +
            nappi_kegs / SIXTEL_PER_BBL +
            nappi_cases / CASES_16OZ_PER_BBL
        )

        # Velocity from each channel (convert to bbl/day)
        mc_brand = mc.get(brand_key, {})
        toast_daily_kegs = mc_brand.get('toast_daily_kegs', 0)
        sd_daily_kegs = mc_brand.get('sd_daily_kegs', 0)

        # Nappi daily rate: convert from units/day to bbl/day
        nappi_daily_cases = nappi.get('nappi_daily_cases', 0)
        nappi_daily_kegs_rate = nappi.get('nappi_daily_kegs', 0)
        nappi_daily_bbl = nappi_daily_cases / CASES_16OZ_PER_BBL + nappi_daily_kegs_rate / SIXTEL_PER_BBL

        # Toast + SelfDist are already in kegs/day, convert to bbl/day
        toast_daily_bbl = toast_daily_kegs / SIXTEL_PER_BBL
        sd_daily_bbl = sd_daily_kegs / SIXTEL_PER_BBL

        # MMM velocity (seasonal, only Jun-Sep of current-ish year)
        mmm_daily_bbl = 0.0
        now_month = int(latest_dt.strftime('%m'))
        if 6 <= now_month <= 9 and toast_data:
            mmm_v = get_mmm_velocity_for_brand(toast_data, brand_key, current_month)
            mmm_daily_bbl = mmm_v.get('daily_kegs', 0) / SIXTEL_PER_BBL

        total_daily_bbl = nappi_daily_bbl + toast_daily_bbl + sd_daily_bbl + mmm_daily_bbl

        # Channel percentages
        channel_pcts = {'nappi': 0, 'toast': 0, 'selfdist': 0, 'mmm': 0}
        if total_daily_bbl > 0:
            channel_pcts = {
                'nappi': round(nappi_daily_bbl / total_daily_bbl * 100),
                'toast': round(toast_daily_bbl / total_daily_bbl * 100),
                'selfdist': round(sd_daily_bbl / total_daily_bbl * 100),
                'mmm': round(mmm_daily_bbl / total_daily_bbl * 100),
            }

        # Days until stockout — per format
        keg_inv_bbl = kegs_sixth / SIXTEL_PER_BBL + kegs_half / HALF_PER_BBL + nappi_kegs / SIXTEL_PER_BBL
        case_inv_bbl = cases_16oz / CASES_16OZ_PER_BBL + cases_12oz / CASES_12OZ_PER_BBL + nappi_cases / CASES_16OZ_PER_BBL

        # Estimate keg vs case demand split from channel data
        # Toast is all draft (kegs), Nappi/SD split by channel_pcts
        keg_demand_share = (channel_pcts.get('toast', 0) + channel_pcts.get('mmm', 0) * 0.0) / 100.0
        case_demand_share = 1.0 - keg_demand_share
        if total_daily_bbl > 0:
            keg_daily = total_daily_bbl * max(keg_demand_share, 0.3)  # at least 30% draft
            case_daily = total_daily_bbl * max(case_demand_share, 0.3)
        else:
            keg_daily = case_daily = 0

        days_stockout_kegs = int(keg_inv_bbl / keg_daily) if keg_daily > 0 else 999
        days_stockout_cases = int(case_inv_bbl / case_daily) if case_daily > 0 else 999
        days_stockout = inv_bbl / total_daily_bbl if total_daily_bbl > 0 else 999
        days_stockout = min(days_stockout, 999)

        # Lead time and batch sizing
        lead_time = brand.get('lead_time_days', DEFAULT_LEAD_TIME_DAYS)
        batch_size = brand.get('batch_size_bbl', DEFAULT_BATCH_SIZE_BBL)

        # Brew status
        brew_urgency = days_stockout - lead_time
        brew_status = "BREW_NOW" if brew_urgency <= 0 else "PLAN" if brew_urgency <= 7 else "OK"

        # Brew-by date
        stockout_dt = latest_dt + timedelta(days=int(days_stockout))
        brew_by_dt = stockout_dt - timedelta(days=lead_time)
        brew_by_date = brew_by_dt.strftime('%Y-%m-%d')

        # Recommended batch: single (7) or double (15)
        # If projected demand over lead_time + 14 days > 7 bbl equivalent → double
        projected_demand = total_daily_bbl * (lead_time + 14)
        recommended_batch = "double" if projected_demand > 7 else "single"
        recommended_bbl = 15 if recommended_batch == "double" else 7

        # Channels list
        channels = []
        if nappi_daily_bbl > 0 or brand.get('nappi_skus'):
            channels.append('nappi')
        if toast_daily_bbl > 0:
            channels.append('toast')
        if sd_daily_bbl > 0 or brand.get('selfdistro'):
            channels.append('selfdistro')
        if mmm_daily_bbl > 0 or brand.get('mmm_names'):
            channels.append('mmm')

        # Seasonality — same month last year
        same_month_ly_bbl = None
        if mc_brand.get('toast_same_month_ly') is not None:
            same_month_ly_bbl = round(mc_brand['toast_same_month_ly'] / SIXTEL_PER_BBL, 3)

        # Trailing 3-month trend
        monthly_trend = mc_brand.get('monthly_trend', [])
        trailing_3mo_trend = 'flat'
        if len(monthly_trend) >= 3:
            recent_3 = [m['daily_kegs'] for m in monthly_trend[-3:]]
            if recent_3[-1] > recent_3[0] * 1.15:
                trailing_3mo_trend = 'up'
            elif recent_3[-1] < recent_3[0] * 0.85:
                trailing_3mo_trend = 'down'

        # Full monthly velocity history (all available months) for seasonality display
        full_monthly_velocity = []
        if toast_data:
            all_months = sorted(toast_data.get('brunswick', {}).get('months', {}).keys())
            for m in all_months:
                m_data = toast_data['brunswick']['months'][m].get('brands', {}).get(brand_key)
                if m_data:
                    full_monthly_velocity.append({
                        'month': m,
                        'daily_kegs': m_data.get('daily_kegs_equiv', 0),
                        'qty_sold': m_data.get('qty_sold', 0),
                    })

        # Channel allocation when batch finishes
        keg_share = max(channel_pcts.get('toast', 0) + channel_pcts.get('mmm', 0), 30) / 100.0
        case_share = 1.0 - keg_share
        kegs_bbl = round(recommended_bbl * keg_share, 1)
        cases_bbl = round(recommended_bbl * case_share, 1)

        # Output estimates: fill 1-2 half-barrels first, rest to sixtels
        halves = min(2, int(kegs_bbl / (1 / HALF_PER_BBL)))  # max 2 halves
        halves = min(halves, int(kegs_bbl * HALF_PER_BBL))
        remaining_bbl = kegs_bbl - halves / HALF_PER_BBL
        remaining_sixtels = max(0, int(remaining_bbl * SIXTEL_PER_BBL))
        parts = []
        if remaining_sixtels > 0:
            parts.append(f"≈{remaining_sixtels} sixtels")
        if halves > 0:
            parts.append(f"{halves} half-barrel{'s' if halves > 1 else ''}")
        kegs_output = " + ".join(parts) if parts else "0 kegs"

        case_size = '12oz' if cases_12oz > 0 and cases_16oz == 0 else '16oz'
        cases_per_bbl = CASES_12OZ_PER_BBL if case_size == '12oz' else CASES_16OZ_PER_BBL
        est_cases = int(cases_bbl * cases_per_bbl)
        cases_output = f"≈{est_cases} cases {case_size}"

        # Channel split for allocation (match HTML keys)
        alloc_split = {
            'nappi': f"{channel_pcts.get('nappi', 0)}%",
            'toast': f"{channel_pcts.get('toast', 0)}%",
            'selfdist': f"{channel_pcts.get('selfdist', 0)}%",
            'mmm': f"{channel_pcts.get('mmm', 0)}%",
        }

        entry = {
            'brand_key': brand_key,
            'display_name': brand.get('display_name', brand_key),
            'style': brand.get('style', ''),
            'channels': channels,
            'brewery_kegs_sixth': kegs_sixth,
            'brewery_kegs_half': kegs_half,
            'brewery_cases_16oz': cases_16oz,
            'brewery_cases_12oz': cases_12oz,
            'nappi_cases': nappi_cases,
            'nappi_kegs': nappi_kegs,
            'total_inv_bbl': round(inv_bbl, 1),
            'nappi_daily_bbl': round(nappi_daily_bbl, 3),
            'toast_daily_bbl': round(toast_daily_bbl, 3),
            'selfdistro_daily_bbl': round(sd_daily_bbl, 3),
            'mmm_daily_bbl': round(mmm_daily_bbl, 3),
            'total_daily_bbl': round(total_daily_bbl, 3),
            'channel_pcts': channel_pcts,
            'days_until_stockout_kegs': min(days_stockout_kegs, 999),
            'days_until_stockout_cases': min(days_stockout_cases, 999),
            'days_until_stockout': round(min(days_stockout, 999)),
            'brew_by_date': brew_by_date,
            'lead_time_days': lead_time,
            'batch_size_bbl': recommended_bbl,
            'recommended_batch': recommended_batch,
            'brew_status': brew_status,
            'priority_rank': 0,  # set below after sorting
            'current_month_velocity_bbl': round(total_daily_bbl, 3),
            'same_month_last_year_bbl': same_month_ly_bbl,
            'trailing_3mo_trend': trailing_3mo_trend,
            'monthly_velocity': full_monthly_velocity,
            'allocation': {
                'total_bbl': recommended_bbl,
                'packaging': {'kegs_bbl': kegs_bbl, 'cases_bbl': cases_bbl},
                'kegs_output': kegs_output,
                'cases_output': cases_output,
                'channel_split': alloc_split,
            },
        }
        production_plan.append(entry)

    # Sort by urgency and assign priority ranks
    production_plan.sort(key=lambda x: x.get('days_until_stockout', 999))
    for i, entry in enumerate(production_plan):
        entry['priority_rank'] = i + 1

    # ── MMM data ──
    mmm_2025_actuals = {
        "2025-06": {"units": 0, "days": 0},
        "2025-07": {"units": 0, "days": 31},
        "2025-08": {"units": 0, "days": 31},
        "2025-09": {"units": 0, "days": 30},
    }
    mmm_brands_set = set()
    if toast_data:
        mmm_months = toast_data.get('mmm', {}).get('months', {})
        for month_key, mdata in mmm_months.items():
            # Map to 2025 slot
            month_num = month_key[5:7]
            target_key = f"2025-{month_num}"
            if target_key in mmm_2025_actuals:
                total_units = sum(b.get('qty_sold', 0) for b in mdata.get('brands', {}).values())
                mmm_2025_actuals[target_key]['units'] = total_units
                mmm_2025_actuals[target_key]['days'] = mdata.get('days_in_period', 30)
            # Collect MMM brand keys
            for bk in mdata.get('brands', {}).keys():
                if bk in brands_cfg:
                    mmm_brands_set.add(bk)

    # ── Brew Calendar ──
    brew_calendar = []
    today = latest_dt
    for entry in production_plan:
        if entry['brew_status'] == 'OK' and entry['days_until_stockout'] > 30:
            continue
        brew_dt = datetime.strptime(entry['brew_by_date'], '%Y-%m-%d')
        delta_days = (brew_dt - today).days
        if delta_days < 0:
            week = 'this_week'
        elif delta_days <= 7:
            week = 'this_week'
        elif delta_days <= 14:
            week = 'next_week'
        elif delta_days <= 21:
            week = 'week_after'
        else:
            continue  # too far out for calendar
        brew_calendar.append({
            'brand_key': entry['brand_key'],
            'display_name': entry['display_name'],
            'brew_by': entry['brew_by_date'],
            'batch': entry['recommended_batch'],
            'status': entry['brew_status'],
            'week': week,
        })

    # Per-brand MMM monthly data for scenario tool
    mmm_brand_monthly = {}
    if toast_data:
        mmm_months_data = toast_data.get('mmm', {}).get('months', {})
        for month_key, mdata in mmm_months_data.items():
            for bk, bdata in mdata.get('brands', {}).items():
                if bk not in mmm_brand_monthly:
                    mmm_brand_monthly[bk] = {}
                mmm_brand_monthly[bk][month_key] = {
                    'qty_sold': bdata.get('qty_sold', 0),
                    'daily_kegs': bdata.get('daily_kegs_equiv', 0),
                }

    # Seasonal index: month → velocity multiplier relative to annual average
    seasonal_index = {}
    if toast_data:
        all_months = toast_data.get('brunswick', {}).get('months', {})
        monthly_totals = {}
        for m_key, m_data in all_months.items():
            month_num = m_key[5:7]  # '01', '02', etc.
            total_kegs = sum(b.get('daily_kegs_equiv', 0) for b in m_data.get('brands', {}).values())
            if month_num not in monthly_totals:
                monthly_totals[month_num] = []
            monthly_totals[month_num].append(total_kegs)
        if monthly_totals:
            avg_all = sum(sum(v) / len(v) for v in monthly_totals.values()) / len(monthly_totals)
            if avg_all > 0:
                for month_num, vals in monthly_totals.items():
                    seasonal_index[month_num] = round(sum(vals) / len(vals) / avg_all, 2)

    planner = {
        'generated': latest_date,
        'data_freshness': data_freshness,
        'production_plan': production_plan,
        'mmm_2025_actuals': mmm_2025_actuals,
        'mmm_brands': sorted(list(mmm_brands_set)),
        'mmm_brand_monthly': mmm_brand_monthly,
        'seasonal_index': seasonal_index,
        'brew_calendar': brew_calendar,
    }

    return planner


def update_dashboard_html(dashboard_data, html_path):
    """Replace the DATA constant in dashboard.html with new data."""
    compact = json.dumps(dashboard_data, separators=(',', ':'), ensure_ascii=False)

    with open(html_path) as f:
        html = f.read()

    replacement = f'const D = {compact};'
    html = re.sub(r'const D = \{.*?\};', lambda m: replacement, html, count=1, flags=re.DOTALL)

    with open(html_path, 'w') as f:
        f.write(html)

    return len(html)


def update_planner_html(planner_data, html_path):
    """Replace the DATA constant in production-planner.html with new data."""
    if not os.path.exists(html_path):
        return 0
    compact = json.dumps(planner_data, separators=(',', ':'), ensure_ascii=False)

    with open(html_path) as f:
        html = f.read()

    replacement = f'const D = {compact};'
    html = re.sub(r'const D = \{.*?\};', lambda m: replacement, html, count=1, flags=re.DOTALL)

    with open(html_path, 'w') as f:
        f.write(html)

    return len(html)


if __name__ == '__main__':
    base = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(base, 'data', 'nappi_data.json')) as f:
        data = json.load(f)

    sku_config = load_sku_config(base)
    if sku_config:
        brands = sku_config.get('brands', {})
        nappi_count = sum(1 for b in brands.values() if b.get('nappi_skus'))
        active_count = sum(1 for b in brands.values() if b.get('active', True))
        print(f"Loaded SKU config: {len(brands)} brands ({nappi_count} Nappi, {active_count} active)")
    else:
        print("No sku_config.json found, using defaults")

    brewery_inv = load_brewery_inventory(base)
    if brewery_inv:
        inv_brands = brewery_inv.get('brands', {})
        print(f"Loaded brewery inventory: {len(inv_brands)} brands (as of {brewery_inv.get('last_updated', '?')})")
    else:
        print("No brewery_inventory.json found, skipping brewery on-hand")
        brewery_inv = {}

    toast_data = load_toast_data(base)
    if toast_data:
        t30 = toast_data.get('brunswick', {}).get('trailing_30d', {})
        n_months = len(toast_data.get('brunswick', {}).get('months', {}))
        mmm_months = len(toast_data.get('mmm', {}).get('months', {}))
        print(f"Loaded Toast data: {n_months} Brunswick months, {mmm_months} MMM months (latest: {t30.get('month', '?')})")
    else:
        print("No toast_data.json found, skipping tasting room velocity")

    sd_data = load_selfdistro_data(base)
    if sd_data:
        sd_months = sorted(sd_data.get('months', {}).keys())
        print(f"Loaded self-distro data: {len(sd_months)} months (latest: {sd_months[-1] if sd_months else '?'})")
    else:
        print("No selfdistro_data.json found, skipping self-distro velocity")

    dashboard = build_dashboard_data(data, sku_config, brewery_inv, toast_data, sd_data)

    compact = json.dumps(dashboard, separators=(',', ':'))
    with open(os.path.join(base, 'data', 'dashboard_data.json'), 'w') as f:
        f.write(compact)
    print(f"Dashboard data: {len(compact)/1024:.1f} KB")

    # Print multi-channel summary
    mc = dashboard.get('multichannel', {})
    if mc:
        print(f"\n=== MULTI-CHANNEL VELOCITY (kegs/day) ===")
        active_brands = [(k, v) for k, v in mc.items() if v.get('total_daily_kegs', 0) > 0]
        active_brands.sort(key=lambda x: x[1]['total_daily_kegs'], reverse=True)
        print(f"{'Brand':30s} {'Toast':>8s} {'SelfDist':>8s} {'Total':>8s}")
        print("-" * 58)
        for bk, v in active_brands:
            print(f"  {v.get('display_name', bk):28s} {v['toast_daily_kegs']:8.3f} {v['sd_daily_kegs']:8.3f} {v['total_daily_kegs']:8.3f}")

    size = update_dashboard_html(dashboard, os.path.join(base, 'dashboard.html'))
    print(f"\nDashboard HTML updated: {size/1024:.1f} KB")

    # Build and update Production Planner
    planner = build_production_planner_data(dashboard, sku_config, brewery_inv, toast_data, sd_data)

    planner_compact = json.dumps(planner, separators=(',', ':'))
    with open(os.path.join(base, 'data', 'planner_data.json'), 'w') as f:
        f.write(planner_compact)
    print(f"Planner data: {len(planner_compact)/1024:.1f} KB ({len(planner['production_plan'])} brands)")

    planner_html = os.path.join(base, 'production-planner.html')
    if os.path.exists(planner_html):
        psize = update_planner_html(planner, planner_html)
        print(f"Production Planner HTML updated: {psize/1024:.1f} KB")

        # Print production plan summary
        plan = planner['production_plan']
        brew_now = [p for p in plan if p['brew_status'] == 'BREW_NOW']
        plan_soon = [p for p in plan if p['brew_status'] == 'PLAN']
        print(f"\n=== PRODUCTION PLAN ===")
        print(f"  BREW NOW: {len(brew_now)} brands")
        for p in brew_now:
            print(f"    {p['display_name']:30s}  {p['total_inv_bbl']:5.1f} bbl inv | {p['total_daily_bbl']:.3f} bbl/d | {p['days_until_stockout']}d left | brew by {p['brew_by_date']}")
        print(f"  PLAN: {len(plan_soon)} brands")
        for p in plan_soon:
            print(f"    {p['display_name']:30s}  {p['total_inv_bbl']:5.1f} bbl inv | {p['total_daily_bbl']:.3f} bbl/d | {p['days_until_stockout']}d left | brew by {p['brew_by_date']}")
    else:
        print("production-planner.html not found, skipping planner update")
