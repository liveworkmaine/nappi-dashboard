#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# fetch_toast_daily.sh — Pull daily Toast POS exports via SFTP
# Flight Deck Brewing — Nappi Dashboard
# ═══════════════════════════════════════════════════════════════
#
# TOAST SFTP Configuration:
#   Host: s-93c7d398bbf24c7a8.server.transfer.toast.com
#   User: FlightDeckDataExportUser
#   Export ID: 2b4287aa-56b5-47e2-9970-35cf9a11cf44
#   Remote Path: /2b4287aa-56b5-47e2-9970-35cf9a11cf44/
#
# The SFTP server contains daily exports with per-order timestamps.
# Key file: ItemSelectionDetails.csv (has individual order lines with timestamps)
#
# SETUP:
#   1. Place your SFTP private key at ~/.ssh/toast_sftp_key
#      (or set TOAST_SFTP_KEY env var to the key path)
#   2. Ensure ssh-keygen and sftp are available
#   3. Run: chmod +x fetch_toast_daily.sh
#
# USAGE:
#   ./fetch_toast_daily.sh              # Fetch last 7 days
#   ./fetch_toast_daily.sh 14           # Fetch last 14 days
#   ./fetch_toast_daily.sh 2026-03-15   # Fetch specific date onward
#
# OUTPUT:
#   data/toast_daily/ — one subfolder per date with CSVs
#
# WORKFLOW:
#   Run this periodically (cron, launchd, or manual) to get daily data.
#   Then run parse_toast_daily.py (future) to integrate into toast_data.json.
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# Configuration
SFTP_HOST="s-93c7d398bbf24c7a8.server.transfer.toast.com"
SFTP_USER="FlightDeckDataExportUser"
EXPORT_ID="2b4287aa-56b5-47e2-9970-35cf9a11cf44"
REMOTE_PATH="/${EXPORT_ID}/"
SFTP_KEY="${TOAST_SFTP_KEY:-$HOME/.ssh/toast_sftp_key}"

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/data/toast_daily"

# Parse arguments
DAYS_BACK=7
START_DATE=""
if [[ "${1:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    START_DATE="$1"
elif [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    DAYS_BACK="$1"
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "═══════════════════════════════════════"
echo "Toast Daily SFTP Fetch"
echo "═══════════════════════════════════════"
echo "Host: $SFTP_HOST"
echo "User: $SFTP_USER"
echo "Key:  $SFTP_KEY"
echo "Output: $OUTPUT_DIR"

# Check key exists
if [[ ! -f "$SFTP_KEY" ]]; then
    echo ""
    echo "ERROR: SFTP key not found at $SFTP_KEY"
    echo ""
    echo "To set up:"
    echo "  1. Get the private key from Toast admin"
    echo "  2. Save it to ~/.ssh/toast_sftp_key"
    echo "  3. chmod 600 ~/.ssh/toast_sftp_key"
    echo "  4. Or set: export TOAST_SFTP_KEY=/path/to/key"
    exit 1
fi

# Calculate date range
if [[ -n "$START_DATE" ]]; then
    echo "Fetching from: $START_DATE to today"
else
    echo "Fetching last $DAYS_BACK days"
fi

# Generate SFTP batch commands
BATCH_FILE=$(mktemp)
trap "rm -f $BATCH_FILE" EXIT

echo "cd $REMOTE_PATH" >> "$BATCH_FILE"
echo "ls -la" >> "$BATCH_FILE"

# List remote directory to find available date folders
# Toast SFTP typically organizes by date: YYYY-MM-DD/
echo ""
echo "Connecting to Toast SFTP..."

# First, list available files/folders
sftp -i "$SFTP_KEY" -oBatchMode=yes -oStrictHostKeyChecking=accept-new \
    "${SFTP_USER}@${SFTP_HOST}" <<EOF 2>&1 | tee /tmp/toast_sftp_listing.txt
cd ${REMOTE_PATH}
ls -la
quit
EOF

echo ""
echo "Remote listing saved to /tmp/toast_sftp_listing.txt"
echo ""

# Now fetch recent files
# Toast daily exports typically have ItemSelectionDetails.csv with:
#   - Order timestamp
#   - Item name
#   - Modifiers (pour size)
#   - Quantity
#   - Price
# Parse these the same way as monthly exports but with daily granularity

echo "Fetching files..."

sftp -i "$SFTP_KEY" -oBatchMode=yes -oStrictHostKeyChecking=accept-new \
    "${SFTP_USER}@${SFTP_HOST}" <<EOF 2>&1
cd ${REMOTE_PATH}
lcd ${OUTPUT_DIR}
mget *.csv
quit
EOF

echo ""
echo "═══════════════════════════════════════"
echo "Done. Files saved to: $OUTPUT_DIR"
echo ""
echo "Next steps:"
echo "  1. Review downloaded files in $OUTPUT_DIR"
echo "  2. Run: python3 parse_toast.py (monthly data)"
echo "  3. Future: python3 parse_toast_daily.py (daily granularity)"
echo "═══════════════════════════════════════"
