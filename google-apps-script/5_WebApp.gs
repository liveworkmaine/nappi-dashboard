/**
 * ============================================================
 * WEB APP
 * ============================================================
 *
 * Serves the dashboard HTML as a web app.
 * The HTML template calls back to getData() to load fresh data
 * from the Google Sheet every time someone opens the page.
 */


/**
 * Serve the dashboard when someone visits the web app URL.
 */
function doGet(e) {
  // Check if this is a data request (AJAX from the dashboard)
  if (e && e.parameter && e.parameter.action === 'getData') {
    const data = getAllSnapshotsFromSheets();
    return ContentService.createTextOutput(JSON.stringify(data))
      .setMimeType(ContentService.MimeType.JSON);
  }

  // Otherwise serve the HTML dashboard
  const template = HtmlService.createTemplateFromFile('Dashboard');
  const output = template.evaluate();
  output.setTitle('Flight Deck Brewing — Distribution Dashboard');
  output.setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  // Make it full-width
  output.addMetaTag('viewport', 'width=device-width, initial-scale=1.0');
  return output;
}


/**
 * Called from the client-side HTML via google.script.run.
 * Returns the full DATA object for the dashboard.
 */
function getData() {
  return getAllSnapshotsFromSheets();
}


/**
 * Include helper for HTML templates (to inline CSS/JS if needed).
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}
