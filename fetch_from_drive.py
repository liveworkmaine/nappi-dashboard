#!/usr/bin/env python3
"""
fetch_from_drive.py — Fetch new Nappi reports from Google Drive and update the dashboard.

Used by GitHub Actions for daily automated updates.
Requires a Google service account with read access to the Nappi Reports folder.

Environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON — JSON string of the service account credentials
  (set as a GitHub Actions secret)
"""

import os
import sys
import json
import re
from datetime import datetime

# Google API
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Local modules
from parse_nappi import parse_sales_comp, parse_accounts, build_daily_snapshot
from build_dashboard_data import build_dashboard_data, update_dashboard_html

FOLDER_ID = '1OG70gPUMeCrYtFGTejqFdx8p1HhOhUt0'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def get_drive_service():
    """Authenticate with Google Drive using service account credentials."""
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
        sys.exit(1)
    creds_info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def list_drive_docs(service):
    """List all Google Docs in the Nappi Reports folder."""
    query = f"'{FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.document'"
    results = service.files().list(q=query, fields="files(id, name)", pageSize=100).execute()
    return results.get('files', [])


def export_doc_text(service, file_id):
    """Export a Google Doc as plain text."""
    content = service.files().export(fileId=file_id, mimeType='text/plain').execute()
    if isinstance(content, bytes):
        content = content.decode('utf-8')
    return content


def parse_doc_name(name):
    """Parse 'YYYY-MM-DD - REPORTTYPE' into (date_str, report_type)."""
    m = re.match(r'(\d{4}-\d{2}-\d{2})\s*-\s*(\w+)', name)
    if m:
        return m.group(1), m.group(2).upper()
    return None, None


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # Load existing data
    data_path = os.path.join(script_dir, 'data', 'nappi_data.json')
    with open(data_path) as f:
        all_data = json.load(f)
    existing_dates = set(all_data.keys())
    print(f"Existing dates: {sorted(existing_dates)}")

    # Connect to Drive
    service = get_drive_service()
    docs = list_drive_docs(service)
    print(f"Found {len(docs)} documents in Drive folder")

    # Group docs by date
    by_date = {}
    for doc in docs:
        date_str, report_type = parse_doc_name(doc['name'])
        if date_str and report_type:
            if date_str not in by_date:
                by_date[date_str] = {}
            by_date[date_str][report_type] = doc

    # Find new dates (need both FLIGHTDECK and RANKALLBRW)
    new_dates = []
    for date_str in sorted(by_date.keys()):
        if date_str not in existing_dates:
            reports = by_date[date_str]
            if 'FLIGHTDECK' in reports and 'RANKALLBRW' in reports:
                new_dates.append(date_str)
            else:
                print(f"  {date_str}: incomplete (have {list(reports.keys())}), skipping")

    if not new_dates:
        print("Dashboard is up to date — no new reports found.")
        return False  # No changes

    print(f"New dates to process: {new_dates}")

    # Fetch and parse each new date
    for date_str in new_dates:
        print(f"\nProcessing {date_str}...")
        reports = by_date[date_str]

        # Fetch text
        fd_text = export_doc_text(service, reports['FLIGHTDECK']['id'])
        ra_text = export_doc_text(service, reports['RANKALLBRW']['id'])

        # Save text files
        text_dir = os.path.join(script_dir, 'text')
        os.makedirs(text_dir, exist_ok=True)
        with open(os.path.join(text_dir, f'FLIGHTDECK_{date_str}.txt'), 'w') as f:
            f.write(fd_text)
        with open(os.path.join(text_dir, f'RANKALLBRW_{date_str}.txt'), 'w') as f:
            f.write(ra_text)

        # Parse
        sc_data = parse_sales_comp(text_content=fd_text)
        ac_data = parse_accounts(text_content=ra_text)
        snapshot = build_daily_snapshot(sc_data, ac_data, date_str)

        # Merge
        all_data[date_str] = snapshot
        print(f"  Added {date_str}: {len(sc_data.get('products', []))} products, {len(ac_data.get('accounts', []))} accounts")

    # Save updated data
    with open(data_path, 'w') as f:
        json.dump(all_data, f, indent=2)

    # Rebuild dashboard
    dashboard = build_dashboard_data(all_data)
    compact = json.dumps(dashboard, separators=(',', ':'))
    with open(os.path.join(script_dir, 'data', 'dashboard_data.json'), 'w') as f:
        f.write(compact)
    update_dashboard_html(dashboard, os.path.join(script_dir, 'dashboard.html'))

    print(f"\nDashboard updated with {len(new_dates)} new date(s): {new_dates}")
    print(f"Total dates now: {len(all_data)}")

    # Report any critical inventory
    for sku, prod in dashboard.get('products', {}).items():
        status = prod.get('inv_status', '')
        if status in ('CRITICAL', 'ORDER_NOW'):
            print(f"  ⚠ {prod['name']}: {status} ({prod.get('days_remaining', '?')} days remaining)")

    return True  # Changes were made


if __name__ == '__main__':
    changed = main()
    # Exit code 0 = changes made (or no changes, both OK)
    # Set output for GitHub Actions
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"has_changes={'true' if changed else 'false'}\n")
