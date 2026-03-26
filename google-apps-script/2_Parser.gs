/**
 * ============================================================
 * PDF TEXT PARSING
 * ============================================================
 *
 * Ported from parse_nappi.py — identical logic in JavaScript.
 * Works with text extracted from PDFs via Google Drive OCR.
 */


/**
 * Preprocess text that may come from Drive OCR (all joined into one line).
 * Re-splits into proper lines by inserting newlines before known patterns.
 */
function preprocessText(text, reportType) {
  const lines = text.trim().split('\n');
  if (lines.length > 10) return text;

  // Auto-detect
  if (!reportType) {
    reportType = (text.indexOf('BREWERY SALES BY ACCOUNT') >= 0 || text.indexOf('PREMISE TOTALS') >= 0)
      ? 'accounts' : 'sales_comp';
  }

  // Split on structural separators
  text = text.replace(/\s*(-{10,})\s*/g, '\n$1\n');
  text = text.replace(/\s*(={10,})\s*/g, '\n$1\n');
  text = text.replace(/\s*(_{10,})\s*/g, '\n$1\n');

  // Section markers
  text = text.replace(/\s+(FLIGHT DECK\s+TOTALS)/g, '\n$1');
  text = text.replace(/\s+(ON PREMISE TOTALS)/g, '\n$1');
  text = text.replace(/\s+(OFF PREMISE TOTALS)/g, '\n$1');
  text = text.replace(/\s+(\*{3,})/g, '\n$1');
  text = text.replace(/\s+(TOTAL SUPPLIER)/g, '\n$1');
  text = text.replace(/\s+(TOTAL FB)/g, '\n$1');

  // Page headers
  text = text.replace(/\s+(COPYRIGHT 1993)/g, '\n$1');
  text = text.replace(/\s+(Page \d+ of \d+)/g, '\n$1');

  if (reportType === 'sales_comp') {
    text = text.replace(/\s+(4500[0-9]|4501[0-9]|4502[0-9]|4503[0-9])\s+FLIGHT DECK/g,
      '\n$1 FLIGHT DECK');
  } else if (reportType === 'accounts') {
    text = text.replace(/([A-Z]{2,})\s+(\d{5}\s+[A-Z][A-Z'])/g, '$1\n$2');
  }

  return text;
}


/**
 * Parse FLIGHTDECK (Sales Comp) report text.
 * Returns { date, products: [...], totals: { mtd_sales, on_hand } }
 */
function parseSalesComp(fullText) {
  fullText = preprocessText(fullText, 'sales_comp');
  const data = { products: [], date: null, totals: {} };

  // Extract date (MM/DD/YY HH:MM)
  const dateMatch = fullText.match(/(\d{1,2}\/\d{1,2}\/\d{2})\s+\d{2}:\d{2}/);
  if (dateMatch) {
    const parts = dateMatch[1].split('/');
    const m = parseInt(parts[0], 10);
    const d = parseInt(parts[1], 10);
    let y = parseInt(parts[2], 10);
    if (y < 100) y += 2000;
    data.date = y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
  }

  const lines = fullText.split('\n');
  for (const line of lines) {
    // Product line: 5-digit SKU followed by FLIGHT DECK ...
    const match = line.match(/^\s*(\d{5})\s+(FLIGHT DECK\s+.+)/);
    if (match) {
      const skuCode = match[1];
      const rest = match[2].trim();
      const tokens = rest.split(/\s+/);

      // Walk tokens to find where numbers begin
      const descParts = [];
      let numStart = 0;
      for (let i = 0; i < tokens.length; i++) {
        if (/^(\d+|---)$/.test(tokens[i])) {
          numStart = i;
          break;
        }
        descParts.push(tokens[i]);
      }
      const desc = descParts.join(' ');
      const numberTokens = tokens.slice(numStart);

      // Parse numbers (--- = 0)
      const nums = [];
      for (const t of numberTokens) {
        if (t === '---') nums.push(0);
        else if (/^\d+$/.test(t)) nums.push(parseInt(t, 10));
      }

      if (nums.length > 0) {
        const mtdSales = nums[0];
        const onHand = nums[nums.length - 1];
        const ytdSales = nums.length > 4 ? nums[4] : mtdSales;

        const skuInfo = SKU_MAP[skuCode] || {};
        data.products.push({
          sku_code: skuCode,
          description: desc,
          product_name: skuInfo.name || desc,
          format: skuInfo.format || '',
          mtd_sales: mtdSales,
          ytd_sales: ytdSales,
          on_hand: onHand,
        });
      }
    }

    // Totals line
    if (line.indexOf('FLIGHT DECK') >= 0 && line.indexOf('TOTALS') >= 0) {
      const nums = line.match(/\d+/g);
      if (nums && nums.length > 0) {
        data.totals.mtd_sales = parseInt(nums[0], 10);
        data.totals.on_hand = parseInt(nums[nums.length - 1], 10);
      }
    }
  }

  return data;
}


/**
 * Parse RANKALLBRW (Accounts) report text.
 * Returns { date, accounts: [...], on_premise_count, off_premise_count, ... }
 */
function parseAccounts(fullText) {
  fullText = preprocessText(fullText, 'accounts');
  const data = {
    accounts: [],
    date: null,
    on_premise_count: 0, off_premise_count: 0,
    on_premise_daily: 0, off_premise_daily: 0,
    on_premise_mtd: 0,   off_premise_mtd: 0,
  };

  // Extract date
  const dateMatch = fullText.match(/(\d{1,2}\/\d{1,2}\/\d{2})\s+\d{2}:\d{2}/);
  if (dateMatch) {
    const parts = dateMatch[1].split('/');
    const m = parseInt(parts[0], 10);
    const d = parseInt(parts[1], 10);
    let y = parseInt(parts[2], 10);
    if (y < 100) y += 2000;
    data.date = y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
  }

  const lines = fullText.split('\n');
  let currentSection = 'on_premise';

  for (const line of lines) {
    // Section transitions
    if (line.indexOf('ON PREMISE') >= 0 && line.indexOf('TOTALS') >= 0) {
      const nums = line.match(/\d+/g);
      if (nums && nums.length >= 3) {
        data.on_premise_daily = parseInt(nums[0], 10);
        data.on_premise_mtd = parseInt(nums[1], 10);
        data.on_premise_count = parseInt(nums[2], 10);
      }
      currentSection = 'off_premise';
      continue;
    }

    if (line.indexOf('OFF PREMISE') >= 0 && line.indexOf('TOTALS') >= 0) {
      const nums = line.match(/\d+/g);
      if (nums && nums.length >= 3) {
        data.off_premise_daily = parseInt(nums[0], 10);
        data.off_premise_mtd = parseInt(nums[1], 10);
        data.off_premise_count = parseInt(nums[2], 10);
      }
      continue;
    }

    if (line.indexOf('TOTAL SUPPLIER') >= 0 || line.indexOf('TOTAL FB') >= 0) continue;

    // Must start with 5-digit account number
    if (!/^\s*\d{5}\s+/.test(line)) continue;

    const acctMatch = line.match(/^\s*(\d{5})\s+(.+)/);
    if (!acctMatch) continue;

    const acctNum = acctMatch[1];
    const rest = acctMatch[2];

    // Find Nappi code (450xx)
    const nappiMatch = rest.match(/\b(450\d{2})\b/);
    if (!nappiMatch) continue;

    const nappiCode = nappiMatch[1];
    const nappiIdx = rest.indexOf(nappiCode);
    let beforeNappi = rest.substring(0, nappiIdx).trim();
    const afterNappi = rest.substring(nappiIdx + nappiCode.length).trim();

    // Parse account info: NAME ADDRESS CITY PHONE
    const phoneMatch = beforeNappi.match(/(\d{3}\s+\d{3}-\d{4})\s*$/);
    let phone = '';
    let nameAddrCity = beforeNappi;
    if (phoneMatch) {
      phone = phoneMatch[1];
      nameAddrCity = beforeNappi.substring(0, phoneMatch.index).trim();
    }

    let city = '';
    let name = nameAddrCity;
    let address = '';

    // Check multi-word cities first
    let foundMulti = false;
    for (const mc of MULTI_WORD_CITIES) {
      if (nameAddrCity.endsWith(mc)) {
        city = mc;
        nameAddrCity = nameAddrCity.substring(0, nameAddrCity.length - mc.length).trim();
        foundMulti = true;
        break;
      }
    }

    if (!foundMulti) {
      const words = nameAddrCity.split(/\s+/);
      if (words.length > 0) {
        city = words[words.length - 1];
        nameAddrCity = words.slice(0, -1).join(' ');
      }
    }

    // Split name and address
    const addrMatch = nameAddrCity.match(/\s(\d+[\s/])/);
    if (addrMatch) {
      name = nameAddrCity.substring(0, addrMatch.index).trim();
      address = nameAddrCity.substring(addrMatch.index).trim();
    } else {
      name = nameAddrCity;
    }

    // Parse product + numbers + salesman (after Nappi code)
    const tokens = afterNappi.split(/\s+/);

    // Walk from end to find salesman (non-numeric tokens)
    const salesmanTokens = [];
    let i = tokens.length - 1;
    while (i >= 0 && !/^\d+$/.test(tokens[i])) {
      salesmanTokens.unshift(tokens[i]);
      i--;
    }
    const salesman = salesmanTokens.join(' ');

    // Remaining tokens: product description + numbers
    const remaining = tokens.slice(0, i + 1);

    // Walk from end to extract numbers
    const numbers = [];
    let j = remaining.length - 1;
    while (j >= 0 && /^\d+$/.test(remaining[j])) {
      numbers.unshift(parseInt(remaining[j], 10));
      j--;
    }

    const productDesc = remaining.slice(0, j + 1).join(' ');

    // Parse: 3 nums (mtd, ytd, sm#) or 4 nums (daily, mtd, ytd, sm#)
    let dailyQty = 0, mtdQty = 0, ytdQty = 0, smNum = '';
    if (numbers.length === 4) {
      dailyQty = numbers[0]; mtdQty = numbers[1]; ytdQty = numbers[2]; smNum = String(numbers[3]);
    } else if (numbers.length === 3) {
      mtdQty = numbers[0]; ytdQty = numbers[1]; smNum = String(numbers[2]);
    } else if (numbers.length === 2) {
      mtdQty = numbers[0]; smNum = String(numbers[1]);
    }

    const skuInfo = SKU_MAP[nappiCode] || {};
    const ceFactor = skuInfo.ceFactor || 1.0;

    data.accounts.push({
      acct_num: acctNum,
      name: name,
      address: address,
      city: city,
      phone: phone,
      nappi_code: nappiCode,
      product_raw: productDesc,
      product_name: skuInfo.name || productDesc,
      product_format: skuInfo.format || '',
      daily_qty: dailyQty,
      mtd_qty: mtdQty,
      ytd_qty: ytdQty,
      actual_daily: Math.round(dailyQty / ceFactor),
      actual_mtd: Math.round(mtdQty / ceFactor),
      salesman: salesman,
      sm_num: smNum,
      premise_type: currentSection,
    });
  }

  return data;
}


/**
 * Build a daily snapshot from parsed sales comp + accounts data.
 * Returns a JSON-ready object matching the dashboard's DATA format.
 */
function buildDailySnapshot(salesCompData, accountsData, reportDate) {
  const sellingDays = parseInt(reportDate.split('-')[2], 10);

  const productsEnriched = [];
  for (const p of (salesCompData.products || [])) {
    const dailySellRate = p.mtd_sales / Math.max(sellingDays, 1);
    const daysOfInventory = dailySellRate > 0 ? p.on_hand / dailySellRate : 999;

    let inventoryStatus;
    if (daysOfInventory <= THRESHOLD_CRITICAL) inventoryStatus = 'CRITICAL';
    else if (daysOfInventory <= THRESHOLD_ORDER_NOW) inventoryStatus = 'ORDER_NOW';
    else if (daysOfInventory <= THRESHOLD_PLAN_PRODUCTION) inventoryStatus = 'PLAN_PRODUCTION';
    else inventoryStatus = 'OK';

    const skuInfo = SKU_MAP[p.sku_code] || {};
    const ceFactor = skuInfo.ceFactor || 1.0;
    const actualMtd = Math.round(p.mtd_sales / ceFactor);
    const actualYtd = Math.round((p.ytd_sales || p.mtd_sales) / ceFactor);
    const actualOnHand = Math.round(p.on_hand / ceFactor);
    const actualDailyRate = Math.round((actualMtd / Math.max(sellingDays, 1)) * 10) / 10;
    const actualUnit = (skuInfo.format || '').indexOf('BBL') >= 0 ? 'kegs' : 'cases';

    productsEnriched.push({
      ...p,
      daily_sell_rate: Math.round(dailySellRate * 100) / 100,
      days_of_inventory: Math.round(daysOfInventory * 10) / 10,
      inventory_status: inventoryStatus,
      ce_factor: ceFactor,
      actual_mtd: actualMtd,
      actual_ytd: actualYtd,
      actual_on_hand: actualOnHand,
      actual_daily_rate: actualDailyRate,
      actual_unit: actualUnit,
    });
  }

  // Account aggregation
  const uniqueAccounts = new Set();
  const accountsWithDaily = new Set();
  const salesmanStats = {};
  const productAccountCount = {};

  for (const a of (accountsData.accounts || [])) {
    uniqueAccounts.add(a.acct_num);
    if (a.daily_qty > 0) accountsWithDaily.add(a.acct_num);

    const sm = a.salesman;
    if (!salesmanStats[sm]) salesmanStats[sm] = { accounts: new Set(), dailyCases: 0, mtdCases: 0 };
    salesmanStats[sm].accounts.add(a.acct_num);
    salesmanStats[sm].dailyCases += a.daily_qty;
    salesmanStats[sm].mtdCases += a.mtd_qty;

    const code = a.nappi_code;
    if (!productAccountCount[code]) productAccountCount[code] = new Set();
    productAccountCount[code].add(a.acct_num);
  }

  const smSummary = {};
  for (const [sm, stats] of Object.entries(salesmanStats)) {
    smSummary[sm] = {
      account_count: stats.accounts.size,
      daily_cases: stats.dailyCases,
      mtd_cases: stats.mtdCases,
    };
  }

  const pacSummary = {};
  for (const [k, v] of Object.entries(productAccountCount)) {
    pacSummary[k] = v.size;
  }

  const totalActualMtd = productsEnriched.reduce((s, p) => s + p.actual_mtd, 0);
  const totalActualOnHand = productsEnriched.reduce((s, p) => s + p.actual_on_hand, 0);

  return {
    date: reportDate,
    sales_comp: {
      products: productsEnriched,
      totals: {
        ...(salesCompData.totals || {}),
        actual_mtd: totalActualMtd,
        actual_on_hand: totalActualOnHand,
      },
    },
    accounts: {
      total_accounts: uniqueAccounts.size,
      accounts_ordering_today: accountsWithDaily.size,
      on_premise_count: accountsData.on_premise_count || 0,
      off_premise_count: accountsData.off_premise_count || 0,
      on_premise_daily: accountsData.on_premise_daily || 0,
      off_premise_daily: accountsData.off_premise_daily || 0,
      on_premise_mtd: accountsData.on_premise_mtd || 0,
      off_premise_mtd: accountsData.off_premise_mtd || 0,
      salesman_summary: smSummary,
      product_distribution: pacSummary,
      detail: accountsData.accounts || [],
    },
  };
}
