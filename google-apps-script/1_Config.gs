/**
 * ============================================================
 * Flight Deck Brewing — Nappi Dashboard (Google Apps Script)
 * ============================================================
 *
 * CONFIGURATION
 *
 * Set these once during initial setup. After that, the daily
 * trigger handles everything automatically.
 */

// ---- EMAIL SETTINGS ----
const NAPPI_SENDER = 'Reports@nappidistributors.com';
const SALES_COMP_SUBJECT = 'Flight Deck Daily Sales Comp';
const ACCOUNTS_SUBJECT = 'Flight Deck Daily Accounts';

// ---- SPREADSHEET ----
// After first run, this gets set automatically via PropertiesService.
// Or you can hardcode it if you create the sheet manually.
function getSpreadsheetId() {
  const props = PropertiesService.getScriptProperties();
  let id = props.getProperty('SPREADSHEET_ID');
  if (!id) {
    // Create the spreadsheet on first run
    const ss = SpreadsheetApp.create('Flight Deck — Nappi Dashboard Data');
    id = ss.getId();
    props.setProperty('SPREADSHEET_ID', id);
    Logger.log('Created new spreadsheet: ' + id);
    initializeSheets_(ss);
  }
  return id;
}

function getSpreadsheet() {
  return SpreadsheetApp.openById(getSpreadsheetId());
}

// ---- CE CONVERSION FACTORS ----
const CE_FACTOR_16OZ_4PK = 1.333;
const CE_FACTOR_12OZ_6PK = 1.0;
const CE_FACTOR_SIXTEL   = 2.296;

// ---- SKU MAP ----
const SKU_MAP = {
  '45000': { name: 'P3 Pale Ale',               format: '4PK CAN', ceFactor: CE_FACTOR_16OZ_4PK },
  '45003': { name: 'P3 Pale Ale',               format: '1/6 BBL', ceFactor: CE_FACTOR_SIXTEL },
  '45005': { name: 'Subhunter IPA',             format: '4PK CAN', ceFactor: CE_FACTOR_16OZ_4PK },
  '45008': { name: 'Subhunter IPA',             format: '1/6 BBL', ceFactor: CE_FACTOR_SIXTEL },
  '45010': { name: 'Wings Hazy IPA',            format: '4PK CAN', ceFactor: CE_FACTOR_16OZ_4PK },
  '45013': { name: 'Wings Hazy IPA',            format: '1/6 BBL', ceFactor: CE_FACTOR_SIXTEL },
  '45015': { name: 'Plane Beer Pilsner',        format: '6PK CAN', ceFactor: CE_FACTOR_12OZ_6PK },
  '45018': { name: 'Plane Beer Pilsner',        format: '1/6 BBL', ceFactor: CE_FACTOR_SIXTEL },
  '45020': { name: 'Remove Before Flight',      format: '4PK CAN', ceFactor: CE_FACTOR_16OZ_4PK },
  '45023': { name: 'Remove Before Flight',      format: '1/6 BBL', ceFactor: CE_FACTOR_SIXTEL },
  '45038': { name: 'Real Maine Italian Pilsner', format: '1/6 BBL', ceFactor: CE_FACTOR_SIXTEL },
};

// ---- INVENTORY THRESHOLDS (days) ----
const THRESHOLD_CRITICAL = 14;
const THRESHOLD_ORDER_NOW = 21;
const THRESHOLD_PLAN_PRODUCTION = 28;

// ---- MULTI-WORD MAINE CITIES ----
const MULTI_WORD_CITIES = [
  'SOUTH PORTLAND', 'SOUTH BERWICK', 'CAPE ELIZABETH',
  'NEW GLOUCESTER', 'BAILEY ISLAND', 'OLD ORCHARD BEACH',
  'NORTH WINDHAM', 'EAST WATERBORO', 'OLD ORCHARD',
];


/**
 * Initialize sheet tabs on first run.
 */
function initializeSheets_(ss) {
  // Rename default sheet
  const defaultSheet = ss.getSheets()[0];
  defaultSheet.setName('SalesComp');
  defaultSheet.appendRow([
    'Date', 'SKU', 'Description', 'ProductName', 'Format',
    'MTD_CE', 'YTD_CE', 'OnHand_CE',
    'DailySellRate', 'DaysOfInventory', 'InventoryStatus',
    'CEFactor', 'ActualMTD', 'ActualYTD', 'ActualOnHand',
    'ActualDailyRate', 'ActualUnit'
  ]);
  defaultSheet.getRange(1, 1, 1, 17).setFontWeight('bold');
  defaultSheet.setFrozenRows(1);

  // Accounts sheet
  const acctSheet = ss.insertSheet('Accounts');
  acctSheet.appendRow([
    'Date', 'AcctNum', 'Name', 'Address', 'City', 'Phone',
    'NappiCode', 'ProductName', 'ProductFormat',
    'DailyQty_CE', 'MTDQty_CE', 'YTDQty_CE',
    'ActualDaily', 'ActualMTD',
    'Salesman', 'SMNum', 'PremiseType'
  ]);
  acctSheet.getRange(1, 1, 1, 17).setFontWeight('bold');
  acctSheet.setFrozenRows(1);

  // DailySummary sheet (one row per date with totals)
  const summSheet = ss.insertSheet('DailySummary');
  summSheet.appendRow([
    'Date', 'TotalAccounts', 'AccountsOrderingToday',
    'OnPremiseCount', 'OffPremiseCount',
    'OnPremiseDaily', 'OffPremiseDaily',
    'OnPremiseMTD', 'OffPremiseMTD',
    'TotalMTD_CE', 'TotalOnHand_CE',
    'TotalActualMTD', 'TotalActualOnHand'
  ]);
  summSheet.getRange(1, 1, 1, 13).setFontWeight('bold');
  summSheet.setFrozenRows(1);

  // ProcessedEmails sheet (tracks which emails have been processed)
  const procSheet = ss.insertSheet('ProcessedEmails');
  procSheet.appendRow(['MessageID', 'Date', 'Subject', 'ProcessedAt']);
  procSheet.getRange(1, 1, 1, 4).setFontWeight('bold');
  procSheet.setFrozenRows(1);

  Logger.log('Sheets initialized successfully');
}
