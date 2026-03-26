# Publishing to GitHub + Daily Auto-Updates

## What's set up

- **`.github/workflows/update-dashboard.yml`** — GitHub Actions workflow that runs at 10:30 PM ET every weekday, fetches new reports from Google Drive, rebuilds the dashboard, and deploys to GitHub Pages
- **`fetch_from_drive.py`** — Standalone Python script that authenticates via Google service account, finds new Nappi reports in Drive, parses them, and updates the dashboard data
- **`.gitignore`** — Excludes PDFs, prototypes, credentials, and Python cache

## Step 1: Create a Google Cloud Service Account

The GitHub Action needs a service account to read from your Google Drive folder.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one), e.g. "nappi-dashboard"
3. Enable the **Google Drive API**:
   - Go to APIs & Services → Library
   - Search "Google Drive API" → Enable
4. Create a Service Account:
   - Go to APIs & Services → Credentials
   - Click "Create Credentials" → "Service Account"
   - Name it something like `nappi-dashboard-reader`
   - No special roles needed (it only reads from a shared folder)
   - Click "Done"
5. Create a key for the service account:
   - Click on the service account you just created
   - Go to "Keys" tab → "Add Key" → "Create new key" → JSON
   - Download the JSON file (keep it safe, never commit it)
6. Share the Google Drive folder with the service account:
   - Copy the service account email (looks like `nappi-dashboard-reader@your-project.iam.gserviceaccount.com`)
   - In Google Drive, find the "Nappi Reports" folder
   - Right-click → Share → paste the service account email → Viewer access → Send

## Step 2: Create the GitHub repo and push

Open Terminal on your Mac, `cd` to the nappi-dashboard folder, and run:

```bash
# Remove the sandbox git artifacts and start fresh
rm -rf .git

# Initialize
git init -b main
git add .gitignore .github/ fetch_from_drive.py requirements.txt \
       SKILL.md ANALYSIS.md build_dashboard_data.py parse_nappi.py \
       dashboard.html data/ text/ google-apps-script/ SETUP_GITHUB.md

git commit -m "Initial commit: Flight Deck distribution dashboard"

# Create the GitHub repo (requires gh CLI — install with: brew install gh)
gh repo create nappi-dashboard --private --source=. --push
```

If you prefer a **public** repo (so the GitHub Pages URL works without Pro), change `--private` to `--public`.

## Step 3: Add the service account secret

```bash
# Paste the contents of the service account JSON file as a secret
gh secret set GOOGLE_SERVICE_ACCOUNT_JSON < ~/path/to/your-service-account-key.json
```

Or do it in the browser:
1. Go to your repo → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `GOOGLE_SERVICE_ACCOUNT_JSON`
4. Value: paste the entire contents of the service account JSON file

## Step 4: Enable GitHub Pages

```bash
# Enable Pages with Actions as the build source
gh api repos/{owner}/{repo}/pages -X POST -f "build_type=workflow" 2>/dev/null || \
gh api repos/{owner}/{repo}/pages -X PUT -f "build_type=workflow"
```

Or in the browser:
1. Go to repo → Settings → Pages
2. Source: "GitHub Actions"

## Step 5: Test it

```bash
# Trigger the workflow manually
gh workflow run update-dashboard.yml

# Watch it run
gh run watch
```

Your dashboard will be live at:
`https://<your-username>.github.io/nappi-dashboard/dashboard.html`

## How the daily cycle works

1. **~6 PM ET** — Nappi emails daily reports to nate@flightdeckbrewing.com
2. **Shortly after** — Your existing Google Apps Script pulls PDFs from Gmail, uploads to Drive, creates OCR'd Google Docs
3. **10:30 PM ET** — GitHub Actions runs `fetch_from_drive.py`:
   - Reads Google Docs from the Nappi Reports Drive folder
   - Compares against already-processed dates in `data/nappi_data.json`
   - Fetches and parses any new reports
   - Rebuilds `dashboard_data.json` and updates `dashboard.html`
   - Commits and pushes changes
4. **Immediately after** — GitHub Pages redeploys with the fresh dashboard

## Troubleshooting

- **Workflow fails with auth error**: Make sure the service account JSON secret is set correctly and the Drive folder is shared with the service account email
- **No new data found**: Check that the Gmail→Drive Google Apps Script is running and creating docs with the expected naming format (`YYYY-MM-DD - REPORTNAME`)
- **Manual refresh**: Go to Actions tab → "Update Dashboard" → "Run workflow" → "Run workflow"
