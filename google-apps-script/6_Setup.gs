/**
 * ============================================================
 * SETUP & TRIGGERS
 * ============================================================
 *
 * Run setupDailyTrigger() once to install the automatic
 * daily email processing. Run initialImport() to backfill
 * any existing emails.
 */


/**
 * ONE-TIME SETUP: Create a daily trigger that runs at 9 AM ET.
 * Run this manually once from the Apps Script editor.
 */
function setupDailyTrigger() {
  // Remove any existing triggers for this function first
  const triggers = ScriptApp.getProjectTriggers();
  for (const t of triggers) {
    if (t.getHandlerFunction() === 'processNewNappiEmails') {
      ScriptApp.deleteTrigger(t);
    }
  }

  // Create new daily trigger at 9 AM Eastern
  ScriptApp.newTrigger('processNewNappiEmails')
    .timeBased()
    .everyDays(1)
    .atHour(9)
    .inTimezone('America/New_York')
    .create();

  Logger.log('Daily trigger created: processNewNappiEmails at 9 AM ET');
}


/**
 * ONE-TIME: Import all existing Nappi emails (backfill).
 * Run this manually once after initial setup to populate
 * historical data from all past emails.
 */
function initialImport() {
  Logger.log('Starting initial import of all Nappi emails...');
  processNewNappiEmails();
  Logger.log('Initial import complete. Check the spreadsheet.');
}


/**
 * UTILITY: Manually reprocess a specific date.
 * Edit the date below and run from the script editor.
 */
function reprocessDate() {
  const TARGET_DATE = '2026-03-12'; // <-- change this
  const ss = getSpreadsheet();

  // Remove existing data for this date
  removeDate_(ss, 'SalesComp', TARGET_DATE);
  removeDate_(ss, 'Accounts', TARGET_DATE);
  removeDate_(ss, 'DailySummary', TARGET_DATE);

  // Also remove from ProcessedEmails so it gets re-fetched
  removeDate_(ss, 'ProcessedEmails', TARGET_DATE);

  Logger.log('Cleared data for ' + TARGET_DATE + '. Running processNewNappiEmails...');
  processNewNappiEmails();
}


/**
 * Remove all rows with a given date from a sheet (column A = date).
 */
function removeDate_(ss, sheetName, dateStr) {
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet || sheet.getLastRow() <= 1) return;

  // Column A or B depending on sheet
  const col = (sheetName === 'ProcessedEmails') ? 2 : 1;
  const data = sheet.getRange(2, col, sheet.getLastRow() - 1, 1).getValues();
  // Delete from bottom up to avoid index shifting
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i][0] === dateStr) {
      sheet.deleteRow(i + 2);
    }
  }
}


/**
 * UTILITY: View the web app URL.
 * After deploying as a web app, this logs the URL.
 */
function showWebAppUrl() {
  const url = ScriptApp.getService().getUrl();
  if (url) {
    Logger.log('Web App URL: ' + url);
  } else {
    Logger.log('Web app not yet deployed. Deploy via Deploy > New deployment > Web app.');
  }
}


/**
 * UTILITY: Test the parser with sample text.
 * Paste sample text below to verify parsing works.
 */
function testParser() {
  const sampleSalesComp = `
3/12/26 08:30
45000 FLIGHT DECK P3 PALE 4PK CN 29 29 --- 29 29 --- 29 29 --- 29 29 --- 59
45005 FLIGHT DECK SUBHUNTER 4PK 23 23 --- 23 23 --- 23 23 --- 23 23 --- 66
FLIGHT DECK  TOTALS 147 147 --- 147 147 --- 147 147 --- 147 147 --- 274
`;

  const result = parseSalesComp(sampleSalesComp);
  Logger.log('Parsed ' + result.products.length + ' products');
  Logger.log('Date: ' + result.date);
  for (const p of result.products) {
    Logger.log('  ' + p.product_name + ' (' + p.format + '): MTD=' + p.mtd_sales + ', OH=' + p.on_hand);
  }
}
