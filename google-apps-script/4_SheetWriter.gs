/**
 * ============================================================
 * SHEET WRITER
 * ============================================================
 *
 * Writes parsed daily snapshots to the Google Sheet tabs.
 * Also reads historical data back out for the dashboard.
 */


/**
 * Write a daily snapshot to all sheet tabs.
 * Skips if the date already exists (idempotent).
 */
function writeSnapshotToSheets_(ss, snapshot, dateStr) {
  // Check if date already exists in DailySummary
  const summSheet = ss.getSheetByName('DailySummary');
  if (summSheet.getLastRow() > 1) {
    const existingDates = summSheet.getRange(2, 1, summSheet.getLastRow() - 1, 1).getValues().flat();
    if (existingDates.indexOf(dateStr) >= 0) {
      Logger.log('  Date ' + dateStr + ' already exists in sheets, skipping.');
      return;
    }
  }

  // 1. Write SalesComp rows
  const scSheet = ss.getSheetByName('SalesComp');
  const scRows = [];
  for (const p of snapshot.sales_comp.products) {
    scRows.push([
      dateStr, p.sku_code, p.description, p.product_name, p.format,
      p.mtd_sales, p.ytd_sales, p.on_hand,
      p.daily_sell_rate, p.days_of_inventory, p.inventory_status,
      p.ce_factor, p.actual_mtd, p.actual_ytd, p.actual_on_hand,
      p.actual_daily_rate, p.actual_unit
    ]);
  }
  if (scRows.length > 0) {
    scSheet.getRange(scSheet.getLastRow() + 1, 1, scRows.length, scRows[0].length).setValues(scRows);
  }

  // 2. Write Accounts rows
  const acSheet = ss.getSheetByName('Accounts');
  const acRows = [];
  for (const a of snapshot.accounts.detail) {
    acRows.push([
      dateStr, a.acct_num, a.name, a.address, a.city, a.phone,
      a.nappi_code, a.product_name, a.product_format,
      a.daily_qty, a.mtd_qty, a.ytd_qty,
      a.actual_daily, a.actual_mtd,
      a.salesman, a.sm_num, a.premise_type
    ]);
  }
  if (acRows.length > 0) {
    acSheet.getRange(acSheet.getLastRow() + 1, 1, acRows.length, acRows[0].length).setValues(acRows);
  }

  // 3. Write DailySummary row
  const acct = snapshot.accounts;
  const totals = snapshot.sales_comp.totals;
  summSheet.appendRow([
    dateStr,
    acct.total_accounts, acct.accounts_ordering_today,
    acct.on_premise_count, acct.off_premise_count,
    acct.on_premise_daily, acct.off_premise_daily,
    acct.on_premise_mtd, acct.off_premise_mtd,
    totals.mtd_sales || 0, totals.on_hand || 0,
    totals.actual_mtd || 0, totals.actual_on_hand || 0
  ]);
}


/**
 * Read all historical data from sheets and rebuild the DATA object
 * that the dashboard expects. Called by the web app's doGet().
 *
 * Returns: { "2026-03-11": { date, sales_comp: {...}, accounts: {...} }, ... }
 */
function getAllSnapshotsFromSheets() {
  const ss = getSpreadsheet();
  const allData = {};

  // Read SalesComp
  const scSheet = ss.getSheetByName('SalesComp');
  if (!scSheet || scSheet.getLastRow() <= 1) return allData;
  const scData = scSheet.getRange(2, 1, scSheet.getLastRow() - 1, 17).getValues();

  // Read Accounts
  const acSheet = ss.getSheetByName('Accounts');
  let acData = [];
  if (acSheet && acSheet.getLastRow() > 1) {
    acData = acSheet.getRange(2, 1, acSheet.getLastRow() - 1, 17).getValues();
  }

  // Read DailySummary
  const summSheet = ss.getSheetByName('DailySummary');
  let summData = [];
  if (summSheet && summSheet.getLastRow() > 1) {
    summData = summSheet.getRange(2, 1, summSheet.getLastRow() - 1, 13).getValues();
  }

  // Index summary by date
  const summByDate = {};
  for (const row of summData) {
    summByDate[row[0]] = {
      total_accounts: row[1],
      accounts_ordering_today: row[2],
      on_premise_count: row[3],
      off_premise_count: row[4],
      on_premise_daily: row[5],
      off_premise_daily: row[6],
      on_premise_mtd: row[7],
      off_premise_mtd: row[8],
      total_mtd_ce: row[9],
      total_oh_ce: row[10],
      total_actual_mtd: row[11],
      total_actual_oh: row[12],
    };
  }

  // Group SalesComp by date
  const scByDate = {};
  for (const row of scData) {
    const date = row[0];
    if (!scByDate[date]) scByDate[date] = [];
    scByDate[date].push({
      sku_code: row[1],
      description: row[2],
      product_name: row[3],
      format: row[4],
      mtd_sales: row[5],
      ytd_sales: row[6],
      on_hand: row[7],
      daily_sell_rate: row[8],
      days_of_inventory: row[9],
      inventory_status: row[10],
      ce_factor: row[11],
      actual_mtd: row[12],
      actual_ytd: row[13],
      actual_on_hand: row[14],
      actual_daily_rate: row[15],
      actual_unit: row[16],
    });
  }

  // Group Accounts by date
  const acByDate = {};
  for (const row of acData) {
    const date = row[0];
    if (!acByDate[date]) acByDate[date] = [];
    acByDate[date].push({
      acct_num: row[1],
      name: row[2],
      address: row[3],
      city: row[4],
      phone: row[5],
      nappi_code: row[6],
      product_name: row[7],
      product_format: row[8],
      daily_qty: row[9],
      mtd_qty: row[10],
      ytd_qty: row[11],
      actual_daily: row[12],
      actual_mtd: row[13],
      salesman: row[14],
      sm_num: row[15],
      premise_type: row[16],
    });
  }

  // Build salesman summaries and product distribution per date
  for (const date of Object.keys(scByDate)) {
    const products = scByDate[date];
    const accounts = acByDate[date] || [];
    const summ = summByDate[date] || {};

    // Salesman summary
    const smStats = {};
    const prodAcctCount = {};
    const uniqueAccts = new Set();
    const actsWithDaily = new Set();

    for (const a of accounts) {
      uniqueAccts.add(a.acct_num);
      if (a.daily_qty > 0) actsWithDaily.add(a.acct_num);

      if (!smStats[a.salesman]) smStats[a.salesman] = { accts: new Set(), daily: 0, mtd: 0 };
      smStats[a.salesman].accts.add(a.acct_num);
      smStats[a.salesman].daily += a.daily_qty;
      smStats[a.salesman].mtd += a.mtd_qty;

      if (!prodAcctCount[a.nappi_code]) prodAcctCount[a.nappi_code] = new Set();
      prodAcctCount[a.nappi_code].add(a.acct_num);
    }

    const smSummary = {};
    for (const [sm, s] of Object.entries(smStats)) {
      smSummary[sm] = { account_count: s.accts.size, daily_cases: s.daily, mtd_cases: s.mtd };
    }
    const pacSummary = {};
    for (const [k, v] of Object.entries(prodAcctCount)) pacSummary[k] = v.size;

    allData[date] = {
      date: date,
      sales_comp: {
        products: products,
        totals: {
          mtd_sales: summ.total_mtd_ce || 0,
          on_hand: summ.total_oh_ce || 0,
          actual_mtd: summ.total_actual_mtd || 0,
          actual_on_hand: summ.total_actual_oh || 0,
        },
      },
      accounts: {
        total_accounts: summ.total_accounts || uniqueAccts.size,
        accounts_ordering_today: summ.accounts_ordering_today || actsWithDaily.size,
        on_premise_count: summ.on_premise_count || 0,
        off_premise_count: summ.off_premise_count || 0,
        on_premise_daily: summ.on_premise_daily || 0,
        off_premise_daily: summ.off_premise_daily || 0,
        on_premise_mtd: summ.on_premise_mtd || 0,
        off_premise_mtd: summ.off_premise_mtd || 0,
        salesman_summary: smSummary,
        product_distribution: pacSummary,
        detail: accounts,
      },
    };
  }

  return allData;
}
