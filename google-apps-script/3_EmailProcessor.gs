/**
 * ============================================================
 * EMAIL PROCESSOR
 * ============================================================
 *
 * Searches Gmail for Nappi report emails, extracts PDF text
 * via Google Drive OCR, parses the data, and writes to Sheets.
 *
 * This runs automatically via a daily time-driven trigger.
 */


/**
 * Main daily processing function. Called by the trigger.
 * Searches for unprocessed Nappi emails, extracts data, writes to sheets.
 */
function processNewNappiEmails() {
  Logger.log('=== Starting Nappi email processing ===');
  const ss = getSpreadsheet();

  // Get list of already-processed message IDs
  const processedIds = getProcessedMessageIds_(ss);

  // Search for Sales Comp emails
  const scThreads = GmailApp.search(
    'from:' + NAPPI_SENDER + ' subject:"' + SALES_COMP_SUBJECT + '" has:attachment',
    0, 50
  );
  // Search for Accounts emails
  const acThreads = GmailApp.search(
    'from:' + NAPPI_SENDER + ' subject:"' + ACCOUNTS_SUBJECT + '" has:attachment',
    0, 50
  );

  Logger.log('Found ' + scThreads.length + ' Sales Comp threads, ' + acThreads.length + ' Accounts threads');

  // Extract messages by date
  const scByDate = {};
  const acByDate = {};

  for (const thread of scThreads) {
    for (const msg of thread.getMessages()) {
      if (processedIds.has(msg.getId())) continue;
      const text = extractTextFromPdfAttachment_(msg);
      if (text) {
        const parsed = parseSalesComp(text);
        if (parsed.date) {
          scByDate[parsed.date] = { parsed: parsed, msgId: msg.getId(), subject: msg.getSubject() };
          Logger.log('  Sales Comp found for date: ' + parsed.date);
        }
      }
    }
  }

  for (const thread of acThreads) {
    for (const msg of thread.getMessages()) {
      if (processedIds.has(msg.getId())) continue;
      const text = extractTextFromPdfAttachment_(msg);
      if (text) {
        const parsed = parseAccounts(text);
        if (parsed.date) {
          acByDate[parsed.date] = { parsed: parsed, msgId: msg.getId(), subject: msg.getSubject() };
          Logger.log('  Accounts found for date: ' + parsed.date);
        }
      }
    }
  }

  // Process each date that has at least one report
  const allDates = [...new Set([...Object.keys(scByDate), ...Object.keys(acByDate)])].sort();

  if (allDates.length === 0) {
    Logger.log('No new emails to process.');
    return;
  }

  for (const dateStr of allDates) {
    Logger.log('Processing date: ' + dateStr);

    const scData = scByDate[dateStr] ? scByDate[dateStr].parsed : { products: [], totals: {} };
    const acData = acByDate[dateStr] ? acByDate[dateStr].parsed : { accounts: [] };

    // Build snapshot
    const snapshot = buildDailySnapshot(scData, acData, dateStr);

    // Write to sheets
    writeSnapshotToSheets_(ss, snapshot, dateStr);

    // Mark messages as processed
    if (scByDate[dateStr]) {
      markMessageProcessed_(ss, scByDate[dateStr].msgId, dateStr, scByDate[dateStr].subject);
    }
    if (acByDate[dateStr]) {
      markMessageProcessed_(ss, acByDate[dateStr].msgId, dateStr, acByDate[dateStr].subject);
    }

    Logger.log('  -> Written to sheets successfully');
  }

  Logger.log('=== Processing complete. ' + allDates.length + ' date(s) processed. ===');
}


/**
 * Extract text from the first PDF attachment in a Gmail message.
 * Uses Google Drive OCR: upload PDF -> convert to Google Doc -> extract text -> clean up.
 */
function extractTextFromPdfAttachment_(message) {
  const attachments = message.getAttachments();
  for (const att of attachments) {
    if (att.getContentType() === 'application/pdf' ||
        att.getName().toLowerCase().endsWith('.pdf')) {

      try {
        // Upload PDF to Drive, requesting OCR conversion to Google Doc
        const blob = att.copyBlob();
        const resource = {
          title: 'nappi_temp_' + new Date().getTime(),
          mimeType: 'application/pdf'
        };

        // Use Drive API to upload with OCR
        const file = Drive.Files.insert(resource, blob, {
          ocr: true,
          ocrLanguage: 'en'
        });

        // Open as Google Doc and extract text
        const doc = DocumentApp.openById(file.id);
        const text = doc.getBody().getText();

        // Clean up temp file
        DriveApp.getFileById(file.id).setTrashed(true);

        if (text && text.trim().length > 50) {
          Logger.log('  Extracted ' + text.length + ' chars from ' + att.getName());
          return text;
        }
      } catch (e) {
        Logger.log('  OCR failed for ' + att.getName() + ': ' + e.message);
        // Fallback: try to read the PDF text directly (works for text-based PDFs)
        try {
          const text = att.getDataAsString();
          if (text && text.indexOf('FLIGHT DECK') >= 0) {
            Logger.log('  Direct text extraction got ' + text.length + ' chars');
            return text;
          }
        } catch (e2) {
          Logger.log('  Direct extraction also failed: ' + e2.message);
        }
      }
    }
  }
  return null;
}


/**
 * Get set of already-processed Gmail message IDs.
 */
function getProcessedMessageIds_(ss) {
  const sheet = ss.getSheetByName('ProcessedEmails');
  const ids = new Set();
  if (sheet.getLastRow() > 1) {
    const data = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
    for (const row of data) {
      if (row[0]) ids.add(row[0]);
    }
  }
  return ids;
}


/**
 * Record that a message has been processed.
 */
function markMessageProcessed_(ss, msgId, dateStr, subject) {
  const sheet = ss.getSheetByName('ProcessedEmails');
  sheet.appendRow([msgId, dateStr, subject, new Date().toISOString()]);
}
