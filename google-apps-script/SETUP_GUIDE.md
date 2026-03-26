# Flight Deck Nappi Dashboard — Google Apps Script Setup

## What This Does

This turns your Nappi distribution dashboard into a live, auto-updating web app hosted entirely in Google's cloud. Every morning at 9 AM ET, it automatically:

1. Searches your Gmail for new Nappi report emails
2. Extracts the PDF text via Google Drive OCR
3. Parses the sales and account data (same logic as the local parser)
4. Writes everything to a Google Sheet (your data store)
5. Anyone with the dashboard URL sees the latest data instantly

No computer needs to be on. No manual steps. Just the daily Nappi emails flowing in.

---

## Setup Steps (15-20 minutes, one time)

### Step 1: Create the Apps Script Project

1. Go to [script.google.com](https://script.google.com)
2. Click **New Project**
3. Name it: `Flight Deck Nappi Dashboard`

### Step 2: Add the Code Files

You need to create 6 script files + 1 HTML file. For each `.gs` file:

1. In the Apps Script editor, click the **+** next to "Files" → **Script**
2. Name it exactly as shown (without the .gs extension — Apps Script adds it)
3. Paste the contents from the corresponding file

Create these files in order:

| File to create | Paste contents from |
|---|---|
| `1_Config` | `1_Config.gs` |
| `2_Parser` | `2_Parser.gs` |
| `3_EmailProcessor` | `3_EmailProcessor.gs` |
| `4_SheetWriter` | `4_SheetWriter.gs` |
| `5_WebApp` | `5_WebApp.gs` |
| `6_Setup` | `6_Setup.gs` |

For the HTML file:

1. Click **+** next to "Files" → **HTML**
2. Name it `Dashboard` (it will become `Dashboard.html`)
3. Paste the contents from `Dashboard.html`

You can delete the default `Code.gs` file that Apps Script created.

### Step 3: Enable the Drive API

The email processor uses Google Drive's OCR to extract text from PDFs:

1. In the Apps Script editor, click **Services** (+ icon) in the left sidebar
2. Scroll down and find **Drive API**
3. Click **Add**

### Step 4: Run Initial Setup

1. In the script editor, select the function **`initialImport`** from the dropdown at the top
2. Click **Run** (▶)
3. You'll be prompted to authorize the app — click through and grant all permissions:
   - Gmail (to read Nappi emails)
   - Drive (for PDF OCR)
   - Sheets (to store data)
4. Check the Execution Log — you should see it finding and processing your existing Nappi emails
5. A new Google Sheet called "Flight Deck — Nappi Dashboard Data" will be created in your Drive

### Step 5: Set Up the Daily Trigger

1. Select **`setupDailyTrigger`** from the function dropdown
2. Click **Run** (▶)
3. This creates an automatic trigger that runs `processNewNappiEmails` every day at 9 AM ET

### Step 6: Deploy as Web App

1. Click **Deploy** → **New deployment**
2. Click the gear icon → **Web app**
3. Settings:
   - **Description**: `Flight Deck Dashboard v1`
   - **Execute as**: `Me`
   - **Who has access**: `Anyone` (or `Anyone with the link` if you prefer)
4. Click **Deploy**
5. Copy the **Web app URL** — this is your shareable dashboard link!

### Step 7: Share It

Send the web app URL to anyone who needs access. They don't need a Google account if you chose "Anyone" access. The dashboard loads fresh data from the Sheet every time it's opened.

---

## Day-to-Day: What Happens Automatically

Every weekday morning at 9 AM ET:

1. The trigger fires `processNewNappiEmails()`
2. It searches Gmail for any unprocessed emails from `Reports@nappidistributors.com`
3. New PDF attachments get OCR'd and parsed
4. Data is written to the Google Sheet
5. Next time someone opens the dashboard URL, they see the new data

**You don't need to do anything.** As long as Nappi keeps sending the daily emails, the dashboard keeps updating.

---

## Troubleshooting

**"No new emails to process"**
- The emails may have already been processed (check the `ProcessedEmails` sheet tab)
- Make sure the email subject lines match exactly: "Flight Deck Daily Sales Comp" and "Flight Deck Daily Accounts"

**Dashboard shows "Loading data..." forever**
- Open the Google Sheet directly and verify data is there
- Check Apps Script execution logs: script.google.com → your project → Executions

**OCR extracted garbled text**
- This happens occasionally with scanned PDFs. The parser has text preprocessing to handle most OCR artifacts
- You can check the `SalesComp` and `Accounts` sheet tabs to see what got parsed

**Want to reprocess a date?**
- Edit the `TARGET_DATE` in `reprocessDate()` and run it from the script editor

**Want to add a new product SKU?**
- Edit the `SKU_MAP` in `1_Config.gs` and add the new entry

**Want to change inventory thresholds?**
- Edit `THRESHOLD_CRITICAL`, `THRESHOLD_ORDER_NOW`, `THRESHOLD_PLAN_PRODUCTION` in `1_Config.gs`

---

## Architecture

```
Gmail (Nappi emails arrive daily)
    ↓
Apps Script Trigger (9 AM ET daily)
    ↓
PDF OCR via Google Drive API
    ↓
Parser (same logic as Python, ported to JS)
    ↓
Google Sheet (structured data store)
    ↓
Web App (serves dashboard HTML)
    ↓
Chart.js dashboard (loads data from Sheet)
```

The Google Sheet has 4 tabs:
- **SalesComp** — one row per SKU per date (product-level data)
- **Accounts** — one row per account-product per date (account detail)
- **DailySummary** — one row per date (aggregate totals)
- **ProcessedEmails** — tracks which Gmail messages have been processed (prevents duplicates)
