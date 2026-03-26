# Flight Deck Brewing — Dashboard Analysis & Recommendations

## 1. DATA AUDIT

### Raw Fields Available (from Nappi reports)
**Per-product (11 SKUs):** sku_code, description, product_name, format, mtd_sales, ytd_sales, on_hand, daily_sell_rate, days_of_inventory, inventory_status, ce_factor, actual_mtd, actual_ytd, actual_on_hand, actual_daily_rate, actual_unit

**Per-account detail (83-126 line items):** acct_num, name, address, city, phone, nappi_code, product_raw, product_name, product_format, daily_qty, mtd_qty, ytd_qty, actual_daily, actual_mtd, salesman, sm_num, premise_type

**Aggregate accounts:** total_accounts, accounts_ordering_today, on_premise_count, off_premise_count, on_premise_daily, off_premise_daily, on_premise_mtd, off_premise_mtd, salesman_summary, product_distribution (accounts per SKU)

### Data NOT Being Surfaced (Opportunities)
1. **Address + phone for every account** — enables "Call these 5 quiet accounts today" with click-to-call links
2. **Product distribution (accounts per SKU)** — shows how many accounts carry each product (product penetration)
3. **Account-level product mix** — which specific products each account carries
4. **YTD data** — available but not shown
5. **Daily qty per account** — can detect who ordered TODAY (daily_qty > 0)
6. **Geographic concentration** — 23 unique cities, Brunswick (14 lines), Portland (11)
7. **On-premise vs off-premise volume split** — not just account counts

### Data We Can't Get from Nappi
- Pricing / revenue (units only)
- Distributor warehouse inventory
- Competitor presence at accounts
- Prior-month historical data
- Account contact names (just business name/phone)
- Delivery schedules

---

## 2. ACTIONABILITY RATINGS

### HIGH — These drive immediate daily decisions
| Metric | Action |
|--------|--------|
| Accounts quiet 7+ days (with phone) | Call them today |
| Brew queue BREW NOW | Start brewing today |
| Accounts ordering today | Leave alone / follow up tomorrow |
| Single-product accounts | Pitch additional SKUs |
| New accounts that haven't reordered | Follow up call within 5 days |

### MEDIUM — Weekly review items
| Metric | Action |
|--------|--------|
| Rep leaderboard | Coaching conversations |
| Product velocity changes | Investigate demand shifts |
| On-hand inventory levels | Plan distributor deliveries |
| Geographic concentration | Route planning |

### LOW — Remove or hide
| Metric | Why |
|--------|-----|
| Format mix (cases vs kegs) | Doesn't drive a decision |
| CE equivalents | Confusing — actual units are better |
| General trend charts | Direction without action |
| MTD totals without targets | Just a number without context |

---

## 3. TOP 5 "MORNING COFFEE" ITEMS (30-second scan)

1. **"Call these accounts"** — Quiet 7+ days, with phone numbers and city
2. **"Brew this"** — Products that will stock out before a new batch is ready
3. **"Who ordered yesterday"** — Today's orders to verify and celebrate
4. **"Rep check"** — Which reps are active vs quiet
5. **"New account follow-up"** — New accounts from last 5 days that need a second order

---

## 4. COMPARISON OF 3 APPROACHES

### Approach A (Mission Control) — Dark, dense, single-scroll
- ✅ Dense KPI strip, stockout timeline, single-scroll layout
- ❌ Dark theme hard to read in bright environments, no action hierarchy

### Approach B (Executive Brief) — Warm editorial
- ✅ Hero numbers with sparklines, narrative callout for brew alerts, timeline feed
- ❌ Too much whitespace, rep cards oversized

### Approach C (War Room) — Sidebar, gamified
- ✅ Sidebar nav, circular inventory gauges, alert cards, podium leaderboard
- ❌ Sidebar wastes mobile space, section switching hides context

---

## 5. RECOMMENDATIONS FOR FINAL BUILD

### Structure: Actions first, data second
- Top: KPI strip (5-6 numbers)
- Below: Plain-English summary ("7 products need brewing. 12 accounts quiet 7+ days.")
- Sections organized by ACTION not data type:
  1. "Today's Actions" (calls, brew decisions, follow-ups)
  2. "Sales" (reps, accounts, trends)
  3. "Production" (inventory, brew queue)

### Critical additions
1. **Phone numbers with tel: links** on quiet account list
2. **Product penetration** — accounts per SKU, track growth
3. **"Ordering today" count** — live activity indicator
4. **Account product mix** — what they carry, what to pitch
5. **Morning brief text** at top in plain English

### Remove
- Format mix section
- Oversized trend charts as primary sections
- CE equivalents (use actual units only)
