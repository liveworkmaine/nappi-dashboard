#!/usr/bin/env python3
"""
Nappi Distributors PDF Report Parser
Parses FLIGHTDECK (Sales Comp) and RANKALLBRW (Accounts) PDFs
"""

import pdfplumber
import re
import json
import sys
import os
from datetime import datetime


def preprocess_text(text, report_type=None):
    """
    Preprocess text content that may come from Google Drive OCR or Gmail preview.
    These sources often join all lines into one long string. This function
    re-splits the text into proper lines by inserting newlines before known
    structural patterns.

    report_type: 'sales_comp' or 'accounts' for context-specific splitting.
                 If None, auto-detects based on content.
    """
    # Always process text to split concatenated lines from Google Drive OCR.
    # Even text with >10 lines may have multiple records on a single line.

    # Strip Google Drive markdown formatting (bold code blocks)
    text = re.sub(r'\*\*`([^`]*)`\*\*', r'\1', text)
    text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)
    text = text.replace('`', '')
    text = text.replace('\\#', '#')
    text = text.replace('\\-', '-')

    # Auto-detect report type if not specified
    if report_type is None:
        if 'BREWERY SALES BY ACCOUNT' in text or 'PREMISE TOTALS' in text:
            report_type = 'accounts'
        else:
            report_type = 'sales_comp'

    # Split on structural separators
    text = re.sub(r'\s*(-{10,})\s*', r'\n\1\n', text)
    text = re.sub(r'\s*(={10,})\s*', r'\n\1\n', text)
    text = re.sub(r'\s*(_{10,})\s*', r'\n\1\n', text)

    # Split before known section markers
    text = re.sub(r'\s+(FLIGHT DECK\s+TOTALS)', r'\n\1', text)
    text = re.sub(r'\s+(ON PREMISE TOTALS)', r'\n\1', text)
    text = re.sub(r'\s+(OFF PREMISE TOTALS)', r'\n\1', text)
    text = re.sub(r'\s+(\*{3,})', r'\n\1', text)
    text = re.sub(r'\s+(TOTAL SUPPLIER)', r'\n\1', text)
    text = re.sub(r'\s+(TOTAL FB)', r'\n\1', text)

    # Split before page headers
    text = re.sub(r'\s+(COPYRIGHT 1993)', r'\n\1', text)
    text = re.sub(r'\s+(Page \d+ of \d+)', r'\n\1', text)

    if report_type == 'sales_comp':
        # Sales Comp: split before product SKU lines (450xx FLIGHT DECK)
        text = re.sub(r'\s+(4500[0-9]|4501[0-9]|4502[0-9]|4503[0-9])\s+FLIGHT DECK',
                       r'\n\1 FLIGHT DECK', text)
    elif report_type == 'accounts':
        # Accounts: split between salesman name ending and next account number.
        # Each line ends with: SM# FIRSTNAME LASTNAME, then next acct# starts.
        # Pattern: uppercase salesman name (2+ chars) then 5-digit acct#
        text = re.sub(r'([A-Z]{2,})\s+(\d{5}\s+[A-Z][A-Z\'])', r'\1\n\2', text)

    return text


# Case equivalent (CE) conversion factors.
# Nappi reports everything in 12oz case equivalents (CEs).
# To get actual units out the door, divide CE by the factor:
#   - 16oz 4pk cans  → 1 case = 1.333 CEs (4×16oz = 64oz vs 4×12oz = 48oz, ratio 64/48)
#   - 12oz 6pk cans  → 1 case = 1.0 CE   (already 12oz base)
#   - 1/6 BBL keg    → 1 keg  = 2.296 CEs (661oz per sixtel / 288oz per case)
CE_FACTOR_16OZ_4PK = 1.333
CE_FACTOR_12OZ_6PK = 1.0
CE_FACTOR_SIXTEL   = 2.296

# Known SKU map for product name normalization
SKU_MAP = {
    "45000": {"name": "P3 Pale Ale", "format": "4PK CAN", "ce_factor": CE_FACTOR_16OZ_4PK},
    "45003": {"name": "P3 Pale Ale", "format": "1/6 BBL", "ce_factor": CE_FACTOR_SIXTEL},
    "45005": {"name": "Subhunter IPA", "format": "4PK CAN", "ce_factor": CE_FACTOR_16OZ_4PK},
    "45008": {"name": "Subhunter IPA", "format": "1/6 BBL", "ce_factor": CE_FACTOR_SIXTEL},
    "45010": {"name": "Wings Hazy IPA", "format": "4PK CAN", "ce_factor": CE_FACTOR_16OZ_4PK},
    "45013": {"name": "Wings Hazy IPA", "format": "1/6 BBL", "ce_factor": CE_FACTOR_SIXTEL},
    "45015": {"name": "Plane Beer Pilsner", "format": "6PK CAN", "ce_factor": CE_FACTOR_12OZ_6PK},
    "45018": {"name": "Plane Beer Pilsner", "format": "1/6 BBL", "ce_factor": CE_FACTOR_SIXTEL},
    "45020": {"name": "Remove Before Flight", "format": "4PK CAN", "ce_factor": CE_FACTOR_16OZ_4PK},
    "45023": {"name": "Remove Before Flight", "format": "1/6 BBL", "ce_factor": CE_FACTOR_SIXTEL},
    "45038": {"name": "Real Maine Italian Pilsner", "format": "1/6 BBL", "ce_factor": CE_FACTOR_SIXTEL},
}


def parse_sales_comp(pdf_path=None, text_content=None):
    """
    Parse FLIGHTDECK.pdf - Sales Comp report.
    Accepts either a PDF path or pre-extracted text content (from Google Drive OCR).

    Format per line:
    45000 FLIGHT DECK P3 PALE 4PK CN 29 29 --- 29 29 --- 29 29 --- 29 29 --- 59

    Columns: SKU DESC [MTD MTD DIFF PCT] x4 sections then ON_HAND
    Since brand is new (all LY values are ---), the repeated MTD values are identical.
    We grab: first number = MTD sales, last number = ON HAND.
    """
    data = {"products": [], "date": None, "totals": {}}

    if text_content:
        full_text = preprocess_text(text_content)
    elif pdf_path:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
    else:
        raise ValueError("Must provide either pdf_path or text_content")

    # Extract date
    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2})\s+\d{2}:\d{2}', full_text)
    if date_match:
        raw_date = date_match.group(1)
        parts = raw_date.split('/')
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        year = 2000 + year if year < 100 else year
        data["date"] = f"{year}-{month:02d}-{day:02d}"

    lines = full_text.split('\n')
    for line in lines:
        # Match product lines: 5-digit SKU followed by FLIGHT DECK ...
        match = re.match(r'\s*(\d{5})\s+(FLIGHT DECK\s+.+)', line)
        if match:
            sku_code = match.group(1)
            rest = match.group(2).strip()

            # Split into tokens
            tokens = rest.split()

            # Walk tokens to find where numeric data begins
            desc_parts = []
            num_start = 0
            for i, tok in enumerate(tokens):
                if re.match(r'^(\d+|---)$', tok):
                    num_start = i
                    break
                desc_parts.append(tok)

            desc = ' '.join(desc_parts)
            number_tokens = tokens[num_start:]

            # Parse numbers (--- = 0)
            nums = []
            for t in number_tokens:
                if t == '---':
                    nums.append(0)
                elif t.isdigit():
                    nums.append(int(t))

            if nums:
                mtd_sales = nums[0]  # First number is MTD
                on_hand = nums[-1]   # Last number is ON HAND
                ytd_sales = nums[4] if len(nums) > 4 else mtd_sales

                sku_info = SKU_MAP.get(sku_code, {})
                product = {
                    "sku_code": sku_code,
                    "description": desc,
                    "product_name": sku_info.get("name", desc),
                    "format": sku_info.get("format", ""),
                    "mtd_sales": mtd_sales,
                    "ytd_sales": ytd_sales,
                    "on_hand": on_hand,
                }
                data["products"].append(product)

        # Totals line
        if 'FLIGHT DECK' in line and 'TOTALS' in line:
            nums = re.findall(r'\d+', line)
            if nums:
                data["totals"]["mtd_sales"] = int(nums[0])
                data["totals"]["on_hand"] = int(nums[-1])

    return data


def parse_accounts(pdf_path=None, text_content=None):
    """
    Parse RANKALLBRW.pdf - Account-level detail report.
    Accepts either a PDF path or pre-extracted text content (from Google Drive OCR).

    Format per line (example):
    11514 ALISSON'S RESTAURANT 11 DOCK SQUARE KENNEBUNKPORT 207 967-4841 45003 FLIGHT DECK P3 PALE 1/6BBL 1 1 34 NICHOLAS WAUGH

    Structure:
    ACCT# NAME ADDRESS CITY PHONE NAPPI_CODE PRODUCT [DAILY] MTD YTD SM# SALESMAN

    When there IS a daily order: 4 trailing numbers (daily, mtd, ytd, sm#) + salesman
    When there is NO daily order: 3 trailing numbers (mtd, ytd, sm#) + salesman

    The NAPPI_CODE (450xx) is key: it separates account info from product info.
    """
    data = {
        "accounts": [],
        "date": None,
        "on_premise_count": 0,
        "off_premise_count": 0,
        "on_premise_daily": 0,
        "off_premise_daily": 0,
        "on_premise_mtd": 0,
        "off_premise_mtd": 0,
    }

    if text_content:
        full_text = preprocess_text(text_content)
    elif pdf_path:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
    else:
        raise ValueError("Must provide either pdf_path or text_content")

    # Extract date
    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2})\s+\d{2}:\d{2}', full_text)
    if date_match:
        raw_date = date_match.group(1)
        parts = raw_date.split('/')
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        year = 2000 + year if year < 100 else year
        data["date"] = f"{year}-{month:02d}-{day:02d}"

    lines = full_text.split('\n')
    current_section = "on_premise"

    for line in lines:
        # Section transitions
        if 'ON PREMISE' in line and 'TOTALS' in line:
            nums = re.findall(r'\d+', line)
            if len(nums) >= 3:
                data["on_premise_daily"] = int(nums[0])
                data["on_premise_mtd"] = int(nums[1])
                data["on_premise_count"] = int(nums[2])
            current_section = "off_premise"
            continue

        if 'OFF PREMISE' in line and 'TOTALS' in line:
            nums = re.findall(r'\d+', line)
            if len(nums) >= 3:
                data["off_premise_daily"] = int(nums[0])
                data["off_premise_mtd"] = int(nums[1])
                data["off_premise_count"] = int(nums[2])
            continue

        if 'TOTAL SUPPLIER' in line or 'TOTAL FB' in line:
            continue

        # Skip header/separator lines
        if not re.match(r'\s*\d{5}\s+', line):
            continue

        # Parse account line
        acct_match = re.match(r'\s*(\d{5})\s+(.+)', line)
        if not acct_match:
            continue

        acct_num = acct_match.group(1)
        rest = acct_match.group(2)

        # Find the Nappi code (450xx) which separates account info from product info
        nappi_match = re.search(r'\b(450\d{2})\b', rest)
        if not nappi_match:
            continue

        nappi_code = nappi_match.group(1)
        before_nappi = rest[:nappi_match.start()].strip()
        after_nappi = rest[nappi_match.end():].strip()

        # Parse account info (before Nappi code): NAME ADDRESS CITY PHONE
        # Format: "ALISSON'S RESTAURANT 11 DOCK SQUARE KENNEBUNKPORT 207 967-4841"
        # City is the last word before the phone area code (with multi-word city handling)
        phone_match = re.search(r'(\d{3}\s+\d{3}-\d{4})\s*$', before_nappi)
        phone = ""
        name_addr_city = before_nappi
        if phone_match:
            phone = phone_match.group(1)
            name_addr_city = before_nappi[:phone_match.start()].strip()

        # Known multi-word Maine cities
        MULTI_WORD_CITIES = [
            'SOUTH PORTLAND', 'SOUTH BERWICK', 'CAPE ELIZABETH',
            'NEW GLOUCESTER', 'BAILEY ISLAND', 'OLD ORCHARD BEACH',
            'NORTH WINDHAM', 'EAST WATERBORO', 'OLD ORCHARD',
        ]

        city = ""
        name = name_addr_city
        address = ""

        # Check for multi-word cities first
        found_multi = False
        for mc in MULTI_WORD_CITIES:
            if name_addr_city.endswith(mc):
                city = mc
                remaining = name_addr_city[:-len(mc)].strip()
                found_multi = True
                break

        if not found_multi:
            # City is the last word
            words = name_addr_city.split()
            if words:
                city = words[-1]
                remaining = ' '.join(words[:-1])
            else:
                remaining = name_addr_city

        # Split remaining into name and address
        # Address typically starts with a number
        addr_match = re.search(r'\s(\d+[\s/])', remaining)
        if addr_match:
            name = remaining[:addr_match.start()].strip()
            address = remaining[addr_match.start():].strip()
        else:
            name = remaining

        # Parse product + numbers + salesman (after Nappi code)
        tokens = after_nappi.split()

        # Walk from end to find salesman name (non-numeric tokens at end)
        salesman_tokens = []
        i = len(tokens) - 1
        while i >= 0 and not tokens[i].isdigit():
            salesman_tokens.insert(0, tokens[i])
            i -= 1
        salesman = ' '.join(salesman_tokens)

        # tokens[0:i+1] is product description + numbers
        remaining = tokens[:i + 1]

        # Walk from end of remaining to extract numbers
        numbers = []
        j = len(remaining) - 1
        while j >= 0 and remaining[j].isdigit():
            numbers.insert(0, int(remaining[j]))
            j -= 1

        # Everything before the numbers is the product description
        product_desc = ' '.join(remaining[:j + 1])

        # Parse numbers: 3 (mtd, ytd, sm#) or 4 (daily, mtd, ytd, sm#)
        daily_qty = 0
        mtd_qty = 0
        ytd_qty = 0
        sm_num = ""

        if len(numbers) == 4:
            daily_qty = numbers[0]
            mtd_qty = numbers[1]
            ytd_qty = numbers[2]
            sm_num = str(numbers[3])
        elif len(numbers) == 3:
            daily_qty = 0
            mtd_qty = numbers[0]
            ytd_qty = numbers[1]
            sm_num = str(numbers[2])
        elif len(numbers) == 2:
            mtd_qty = numbers[0]
            sm_num = str(numbers[1])

        sku_info = SKU_MAP.get(nappi_code, {})
        ce_factor = sku_info.get("ce_factor", 1.0)

        account = {
            "acct_num": acct_num,
            "name": name,
            "address": address,
            "city": city,
            "phone": phone,
            "nappi_code": nappi_code,
            "product_raw": product_desc,
            "product_name": sku_info.get("name", product_desc),
            "product_format": sku_info.get("format", ""),
            "daily_qty": daily_qty,
            "mtd_qty": mtd_qty,
            "ytd_qty": ytd_qty,
            "actual_daily": round(daily_qty / ce_factor),
            "actual_mtd": round(mtd_qty / ce_factor),
            "salesman": salesman,
            "sm_num": sm_num,
            "premise_type": current_section,
        }
        data["accounts"].append(account)

    return data


def build_daily_snapshot(sales_comp_data, accounts_data, report_date):
    """Combine parsed data into a single daily snapshot for the JSON store."""

    # Calculate sell-through metrics
    selling_days_in_month = int(report_date.split('-')[2])

    products_enriched = []
    for p in sales_comp_data.get("products", []):
        daily_sell_rate = p["mtd_sales"] / max(selling_days_in_month, 1)
        days_of_inventory = p["on_hand"] / daily_sell_rate if daily_sell_rate > 0 else 999

        if days_of_inventory <= 14:
            inventory_status = "CRITICAL"
        elif days_of_inventory <= 21:
            inventory_status = "ORDER_NOW"
        elif days_of_inventory <= 28:
            inventory_status = "PLAN_PRODUCTION"
        else:
            inventory_status = "OK"

        # Convert CEs to actual units (cases or kegs).
        # Nappi rounds CEs to the nearest whole number, so the converted
        # result should also be rounded to the nearest whole unit — you
        # can't sell half a case or half a keg.
        sku_info = SKU_MAP.get(p.get("sku_code", ""), {})
        ce_factor = sku_info.get("ce_factor", 1.0)
        actual_mtd = round(p["mtd_sales"] / ce_factor)
        actual_ytd = round(p.get("ytd_sales", p["mtd_sales"]) / ce_factor)
        actual_on_hand = round(p["on_hand"] / ce_factor)
        # Daily rate keeps one decimal since it's a calculated average
        actual_daily_rate = round(actual_mtd / max(selling_days_in_month, 1), 1)
        actual_unit = "kegs" if "BBL" in sku_info.get("format", "") else "cases"

        products_enriched.append({
            **p,
            "daily_sell_rate": round(daily_sell_rate, 2),
            "days_of_inventory": round(days_of_inventory, 1),
            "inventory_status": inventory_status,
            "ce_factor": ce_factor,
            "actual_mtd": actual_mtd,
            "actual_ytd": actual_ytd,
            "actual_on_hand": actual_on_hand,
            "actual_daily_rate": actual_daily_rate,
            "actual_unit": actual_unit,
        })

    # Aggregate account-level stats
    unique_accounts = set()
    accounts_with_daily = set()
    salesman_stats = {}
    product_account_count = {}

    for a in accounts_data.get("accounts", []):
        unique_accounts.add(a["acct_num"])
        if a["daily_qty"] > 0:
            accounts_with_daily.add(a["acct_num"])

        sm = a["salesman"]
        if sm not in salesman_stats:
            salesman_stats[sm] = {"accounts": set(), "daily_cases": 0, "mtd_cases": 0}
        salesman_stats[sm]["accounts"].add(a["acct_num"])
        salesman_stats[sm]["daily_cases"] += a["daily_qty"]
        salesman_stats[sm]["mtd_cases"] += a["mtd_qty"]

        code = a["nappi_code"]
        if code not in product_account_count:
            product_account_count[code] = set()
        product_account_count[code].add(a["acct_num"])

    sm_summary = {}
    for sm, stats in salesman_stats.items():
        sm_summary[sm] = {
            "account_count": len(stats["accounts"]),
            "daily_cases": stats["daily_cases"],
            "mtd_cases": stats["mtd_cases"],
        }

    pac_summary = {k: len(v) for k, v in product_account_count.items()}

    # Compute actual-unit totals (sum of already-rounded per-SKU values)
    total_actual_mtd = sum(p["actual_mtd"] for p in products_enriched)
    total_actual_on_hand = sum(p["actual_on_hand"] for p in products_enriched)
    raw_totals = sales_comp_data.get("totals", {})

    snapshot = {
        "date": report_date,
        "sales_comp": {
            "products": products_enriched,
            "totals": {
                **raw_totals,
                "actual_mtd": total_actual_mtd,
                "actual_on_hand": total_actual_on_hand,
            },
        },
        "accounts": {
            "total_accounts": len(unique_accounts),
            "accounts_ordering_today": len(accounts_with_daily),
            "on_premise_count": accounts_data.get("on_premise_count", 0),
            "off_premise_count": accounts_data.get("off_premise_count", 0),
            "on_premise_daily": accounts_data.get("on_premise_daily", 0),
            "off_premise_daily": accounts_data.get("off_premise_daily", 0),
            "on_premise_mtd": accounts_data.get("on_premise_mtd", 0),
            "off_premise_mtd": accounts_data.get("off_premise_mtd", 0),
            "salesman_summary": sm_summary,
            "product_distribution": pac_summary,
            "detail": accounts_data.get("accounts", []),
        },
    }

    return snapshot


if __name__ == "__main__":
    import glob

    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "data")
    pdf_dir = os.path.join(script_dir, "pdfs")
    text_dir = os.path.join(script_dir, "text")

    # Find all PDF pairs
    sc_files = sorted(glob.glob(os.path.join(pdf_dir, "FLIGHTDECK_*.pdf")))
    ac_files = sorted(glob.glob(os.path.join(pdf_dir, "RANKALLBRW_*.pdf")))

    sc_by_date = {}
    for f in sc_files:
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', f)
        if date_match:
            sc_by_date[date_match.group(1)] = ("pdf", f)

    ac_by_date = {}
    for f in ac_files:
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', f)
        if date_match:
            ac_by_date[date_match.group(1)] = ("pdf", f)

    # Find text files (from Google Drive OCR) — these take precedence if no PDF
    if os.path.isdir(text_dir):
        sc_txt_files = sorted(glob.glob(os.path.join(text_dir, "FLIGHTDECK_*.txt")))
        ac_txt_files = sorted(glob.glob(os.path.join(text_dir, "RANKALLBRW_*.txt")))

        for f in sc_txt_files:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', f)
            if date_match and date_match.group(1) not in sc_by_date:
                sc_by_date[date_match.group(1)] = ("text", f)

        for f in ac_txt_files:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', f)
            if date_match and date_match.group(1) not in ac_by_date:
                ac_by_date[date_match.group(1)] = ("text", f)

    all_snapshots = {}

    for date_str in sorted(set(list(sc_by_date.keys()) + list(ac_by_date.keys()))):
        print(f"\n{'='*60}")
        print(f"Processing date: {date_str}")
        print(f"{'='*60}")

        sc_data = {"products": [], "totals": {}}
        ac_data = {"accounts": []}

        if date_str in sc_by_date:
            src_type, src_path = sc_by_date[date_str]
            print(f"  Parsing Sales Comp ({src_type}): {src_path}")
            if src_type == "pdf":
                sc_data = parse_sales_comp(pdf_path=src_path)
            else:
                with open(src_path) as f:
                    sc_data = parse_sales_comp(text_content=f.read())
            print(f"  -> Found {len(sc_data['products'])} products")
            print(f"  -> Totals: MTD={sc_data['totals'].get('mtd_sales', 'N/A')}, OH={sc_data['totals'].get('on_hand', 'N/A')}")
            for p in sc_data['products']:
                print(f"     {p['sku_code']} {p['description']}: MTD={p['mtd_sales']}, OH={p['on_hand']}")

        if date_str in ac_by_date:
            src_type, src_path = ac_by_date[date_str]
            print(f"  Parsing Accounts ({src_type}): {src_path}")
            if src_type == "pdf":
                ac_data = parse_accounts(pdf_path=src_path)
            else:
                with open(src_path) as f:
                    ac_data = parse_accounts(text_content=f.read())
            print(f"  -> Found {len(ac_data['accounts'])} account-product rows")
            print(f"  -> On-premise: {ac_data.get('on_premise_count', 0)} accounts")
            print(f"  -> Off-premise: {ac_data.get('off_premise_count', 0)} accounts")
            for a in ac_data['accounts'][:5]:
                print(f"     {a['acct_num']} {a['name']} | {a['city']} | {a['nappi_code']} {a['product_name']} ({a['product_format']}) | D={a['daily_qty']} M={a['mtd_qty']} | {a['salesman']}")

        snapshot = build_daily_snapshot(sc_data, ac_data, date_str)
        all_snapshots[date_str] = snapshot

    # Save combined data store
    output_path = os.path.join(data_dir, "nappi_data.json")
    with open(output_path, 'w') as f:
        json.dump(all_snapshots, f, indent=2)
    print(f"\n{'='*60}")
    print(f"Saved data store to {output_path}")
    print(f"Total dates: {len(all_snapshots)}")
