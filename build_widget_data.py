#!/usr/bin/env python3
"""
Build consumer-facing Beer Finder widget data from nappi_data.json.

Outputs widget_data.json with:
  - Deduplicated account list with products, freshness, contact info
  - Geocoded lat/lng for map display
  - Separate on_premise / off_premise groupings
  - Report date and freshness metadata

Geocoding uses Nominatim (OpenStreetMap) with a local cache file
to avoid re-geocoding known addresses.
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime


GEOCODE_CACHE_FILE = "data/geocode_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "FlightDeckBeerFinder/1.0 (nate@flightdeckbrewing.com)"
FRESHNESS_DAYS_WARN = 21  # days without reorder before "may be unavailable"

# City-level coordinates for southern Maine (fallback when Nominatim is unavailable)
MAINE_CITY_COORDS = {
    "PORTLAND": (43.6591, -70.2568),
    "SOUTH PORTLAND": (43.6415, -70.2409),
    "BRUNSWICK": (43.9145, -69.9653),
    "FREEPORT": (43.8573, -70.1031),
    "YARMOUTH": (43.8001, -70.1868),
    "BIDDEFORD": (43.4926, -70.4534),
    "SACO": (43.5009, -70.4428),
    "KENNEBUNKPORT": (43.3617, -70.4773),
    "KENNEBUNK": (43.3839, -70.5445),
    "WELLS": (43.3223, -70.5806),
    "KITTERY": (43.0880, -70.7356),
    "YORK": (43.1612, -70.6489),
    "ELIOT": (43.1540, -70.7990),
    "SCARBOROUGH": (43.5785, -70.3218),
    "CAPE ELIZABETH": (43.5638, -70.2001),
    "GORHAM": (43.6795, -70.4443),
    "WESTBROOK": (43.6770, -70.3712),
    "GRAY": (43.8876, -70.3318),
    "CUMBERLAND": (43.7955, -70.2561),
    "SANFORD": (43.4393, -70.7744),
    "SPRINGVALE": (43.4687, -70.7917),
    "LYMAN": (43.4695, -70.6466),
    "NAPLES": (43.9745, -70.5886),
    "BUXTON": (43.6396, -70.5279),
    "NORTH WINDHAM": (43.8361, -70.4298),
    "NEW GLOUCESTER": (43.9632, -70.3052),
    "EAST WATERBORO": (43.5638, -70.7286),
    "BAILEY ISLAND": (43.7440, -69.9920),
    "SOUTH BERWICK": (43.2326, -70.8088),
    "OLD ORCHARD BEACH": (43.5173, -70.3774),
}


def load_geocode_cache(base_dir):
    cache_path = os.path.join(base_dir, GEOCODE_CACHE_FILE)
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
    return {}


def save_geocode_cache(cache, base_dir):
    cache_path = os.path.join(base_dir, GEOCODE_CACHE_FILE)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)


def geocode_address(address, city, state="ME", cache=None):
    """
    Geocode an address using Nominatim. Returns (lat, lng) or (None, None).
    Uses cache to avoid redundant API calls.
    """
    if not address and not city:
        return None, None

    # Build a cache key from the normalized address
    cache_key = f"{address}, {city}, {state}".upper().strip()
    if cache and cache_key in cache:
        cached = cache[cache_key]
        return cached.get("lat"), cached.get("lng")

    # Build the query — try full address first, fall back to city
    if address:
        query = f"{address}, {city}, {state}"
    else:
        query = f"{city}, {state}"

    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    })

    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode())

        if results:
            lat = float(results[0]["lat"])
            lng = float(results[0]["lon"])
            if cache is not None:
                cache[cache_key] = {"lat": lat, "lng": lng}
            return lat, lng
        else:
            # Try city-only fallback
            if address:
                time.sleep(1.1)  # respect Nominatim rate limit
                return geocode_address("", city, state, cache)
            if cache is not None:
                cache[cache_key] = {"lat": None, "lng": None}
            return None, None

    except Exception as e:
        print(f"  Geocode error for '{query}': {e}")
        if cache is not None:
            cache[cache_key] = {"lat": None, "lng": None}
        return None, None


def build_widget_data(nappi_data):
    """
    Build consumer-facing widget data from the full nappi_data.json.

    Returns a dict with:
      - report_date: latest report date
      - on_draft: list of on-premise locations
      - in_stores: list of off-premise locations
      - beers: list of beer names/styles for legend
    """
    dates = sorted(nappi_data.keys())
    latest_date = dates[-1]
    latest = nappi_data[latest_date]

    # Build a map of all accounts across all dates, tracking last order
    all_accounts = {}
    prev_mtd = {}

    for d in dates:
        detail = nappi_data[d]["accounts"].get("detail", [])
        for a in detail:
            acct = a["acct_num"]
            sku = a["nappi_code"]
            key = (acct, sku)
            curr = a["mtd_qty"]

            # Initialize account if first time seeing it
            if acct not in all_accounts:
                all_accounts[acct] = {
                    "name": a["name"],
                    "address": a.get("address", ""),
                    "city": a.get("city", ""),
                    "state": "ME",
                    "phone": a.get("phone", ""),
                    "type": a["premise_type"],
                    "products": {},
                    "last_order_date": d,
                }

            # Track product
            product_name = a.get("product_name", a.get("product_raw", ""))
            product_format = a.get("product_format", "")
            all_accounts[acct]["products"][sku] = {
                "name": product_name,
                "format": product_format,
            }

            # Detect new orders (MTD increased)
            prev = prev_mtd.get(key, 0)
            if curr > prev:
                all_accounts[acct]["last_order_date"] = d

            prev_mtd[key] = curr

    # Calculate days since last order for each account
    latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")

    locations = []
    for acct_id, acct in all_accounts.items():
        last_order_dt = datetime.strptime(acct["last_order_date"], "%Y-%m-%d")
        days_since = (latest_dt - last_order_dt).days

        # Determine freshness status
        if days_since <= 7:
            freshness = "fresh"
            freshness_label = "Ordered this week"
        elif days_since <= FRESHNESS_DAYS_WARN:
            freshness = "recent"
            freshness_label = f"Ordered {days_since} days ago"
        else:
            freshness = "stale"
            freshness_label = f"Last ordered {days_since}+ days ago — may be unavailable"

        # Format product list for consumers
        products = []
        for sku, info in acct["products"].items():
            # Consumer-friendly format
            if "BBL" in info["format"]:
                serve_type = "On Draft"
            elif "4PK" in info["format"] or "6PK" in info["format"]:
                serve_type = "Cans"
            else:
                serve_type = ""
            products.append({
                "name": info["name"],
                "type": serve_type,
            })

        # Deduplicate products (same beer might appear in multiple formats)
        seen = set()
        unique_products = []
        for p in products:
            key = f"{p['name']}|{p['type']}"
            if key not in seen:
                seen.add(key)
                unique_products.append(p)

        # Format phone for display
        phone = acct["phone"]
        if phone:
            phone = phone.replace(" ", "-")  # "207 967-4841" → "207-967-4841"

        # Build directions query
        addr_parts = [acct["address"], acct["city"], "ME"]
        directions_query = ", ".join(p for p in addr_parts if p)

        location = {
            "id": acct_id,
            "name": title_case_name(acct["name"]),
            "address": title_case_name(acct["address"]),
            "city": title_case_name(acct["city"]),
            "state": "ME",
            "phone": phone,
            "phone_raw": phone.replace("-", ""),
            "type": acct["type"],
            "products": unique_products,
            "last_order": acct["last_order_date"],
            "days_since_order": days_since,
            "freshness": freshness,
            "freshness_label": freshness_label,
            "directions_query": directions_query,
            "lat": None,
            "lng": None,
        }
        locations.append(location)

    # Sort: fresh first, then by name
    freshness_order = {"fresh": 0, "recent": 1, "stale": 2}
    locations.sort(key=lambda x: (freshness_order.get(x["freshness"], 9), x["name"]))

    # Separate by type
    on_draft = [l for l in locations if l["type"] == "on_premise"]
    in_stores = [l for l in locations if l["type"] != "on_premise"]

    # Build beer list for legend
    all_beers = set()
    for loc in locations:
        for p in loc["products"]:
            all_beers.add(p["name"])

    widget_data = {
        "report_date": latest_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "freshness_threshold_days": FRESHNESS_DAYS_WARN,
        "on_draft": on_draft,
        "in_stores": in_stores,
        "beers": sorted(all_beers),
        "total_locations": len(locations),
    }

    return widget_data


def title_case_name(name):
    """Convert ALL CAPS names to Title Case, handling apostrophes and common patterns."""
    if not name:
        return name

    # Words that should stay lowercase (unless first word)
    small_words = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for"}

    words = name.lower().split()
    result = []
    for i, word in enumerate(words):
        # Handle apostrophes: "alisson's" → "Alisson's"
        # Only capitalize the part before the apostrophe; keep short suffixes lowercase
        if "'" in word:
            parts = word.split("'")
            result_parts = [parts[0].capitalize()]
            for p in parts[1:]:
                # Short possessive suffixes stay lowercase: 's, t, re, etc.
                if len(p) <= 2:
                    result_parts.append(p)
                else:
                    result_parts.append(p.capitalize())
            word = "'".join(result_parts)
        elif i == 0 or word not in small_words:
            word = word.capitalize()
        # Handle "STE" → "Ste", "AVE" → "Ave" etc.
        result.append(word)

    return " ".join(result)


def geocode_all(widget_data, base_dir, use_nominatim=True):
    """
    Geocode all locations in the widget data.
    Uses cache first, then Nominatim (if enabled), then city-level fallback.
    """
    cache = load_geocode_cache(base_dir)
    all_locations = widget_data["on_draft"] + widget_data["in_stores"]
    total = len(all_locations)
    exact = 0
    city_fallback = 0

    for i, loc in enumerate(all_locations):
        addr = loc["address"]
        city = loc["city"]

        # Check cache first
        cache_key = f"{addr}, {city}, ME".upper().strip()
        if cache_key in cache and cache[cache_key].get("lat") is not None:
            loc["lat"] = cache[cache_key]["lat"]
            loc["lng"] = cache[cache_key]["lng"]
            exact += 1
            print(f"  [{i+1}/{total}] {loc['name']}, {city}: cached ({loc['lat']:.4f}, {loc['lng']:.4f})")
            continue

        # Try Nominatim if enabled
        if use_nominatim:
            lat, lng = geocode_address(addr, city, "ME", cache)
            if lat is not None:
                loc["lat"] = lat
                loc["lng"] = lng
                exact += 1
                print(f"  [{i+1}/{total}] {loc['name']}, {city}: ({lat:.4f}, {lng:.4f})")
                time.sleep(2.0)
                continue
            time.sleep(2.0)

        # Fall back to city-level coordinates
        city_upper = city.upper().strip() if city else ""
        if city_upper in MAINE_CITY_COORDS:
            lat, lng = MAINE_CITY_COORDS[city_upper]
            # Add small random offset so pins don't stack exactly
            import random
            lat += random.uniform(-0.003, 0.003)
            lng += random.uniform(-0.003, 0.003)
            loc["lat"] = round(lat, 5)
            loc["lng"] = round(lng, 5)
            city_fallback += 1
            print(f"  [{i+1}/{total}] {loc['name']}, {city}: city-level ({loc['lat']:.4f}, {loc['lng']:.4f})")
        else:
            print(f"  [{i+1}/{total}] {loc['name']}, {city}: NO COORDS")

    save_geocode_cache(cache, base_dir)
    geocoded = sum(1 for l in all_locations if l["lat"] is not None)
    print(f"\nGeocoded {geocoded}/{total} ({exact} exact, {city_fallback} city-level)")


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base, "data", "nappi_data.json")

    with open(data_path) as f:
        nappi_data = json.load(f)

    print("Building widget data...")
    widget_data = build_widget_data(nappi_data)
    print(f"  On Draft: {len(widget_data['on_draft'])} locations")
    print(f"  In Stores: {len(widget_data['in_stores'])} locations")
    print(f"  Total: {widget_data['total_locations']}")
    print(f"  Beers: {', '.join(widget_data['beers'])}")

    print("\nGeocoding addresses (cache + city fallback)...")
    geocode_all(widget_data, base, use_nominatim=False)

    # Save output
    output_path = os.path.join(base, "data", "widget_data.json")
    with open(output_path, "w") as f:
        json.dump(widget_data, f, indent=2)
    print(f"\nSaved widget data to {output_path}")
    print(f"Size: {os.path.getsize(output_path) / 1024:.1f} KB")

    # Build Squarespace-ready version with data inlined
    html_path = os.path.join(base, "beer-finder.html")
    if os.path.exists(html_path):
        import re as re_mod
        with open(html_path) as f:
            html = f.read()

        compact = json.dumps(widget_data, separators=(",", ":"))
        # Replace the null placeholder with actual data
        html_inline = re_mod.sub(
            r"let WIDGET_DATA = null;",
            f"let WIDGET_DATA = {compact};",
            html,
            count=1,
        )

        inline_path = os.path.join(base, "beer-finder-inline.html")
        with open(inline_path, "w") as f:
            f.write(html_inline)
        print(f"Saved inline widget to {inline_path}")
        print(f"Size: {os.path.getsize(inline_path) / 1024:.1f} KB")
