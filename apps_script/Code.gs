/**
 * Write endpoint for Navy Recruiting Sheet 2.0 — "High School Players" tab.
 *
 * This is NOT deployed from git. Paste this file's contents into the Sheet's
 * own Apps Script editor (Extensions -> Apps Script) and deploy as a Web App.
 * See README in this folder for exact steps.
 *
 * Why this exists instead of a GCP service account: Chris's GCP org enforces
 * iam.disableServiceAccountKeyCreation, which blocks the usual way a backend
 * authenticates to write to a Sheet. Apps Script bound to the Sheet runs with
 * the deploying user's own permissions, so it sidesteps that restriction
 * entirely - no GCP project, no service account, no OAuth flow.
 *
 * Column map (1-indexed, matches Sheets' native getRange(row, col)).
 * Verified against the real header row 2026-06-30 - do not guess, re-verify
 * against row 3 of the live sheet if this ever looks wrong:
 *   4  = Name (composite label, e.g. "Noah Stead (0.1) - '25 MINF CA")
 *   8  = First Name
 *   9  = Last Name
 *   10 = Class
 *   11 = ★ (tier/rating)
 *   12 = Commit
 *   13 = Pos
 *   17 = State
 *   18 = High School
 *   19 = Summer Team
 *   23 = Seen
 * Data rows start at row 4 (rows 1-3 are header/legend).
 */

var SHEET_NAME = 'High School Players';
var DATA_START_ROW = 4;

function doPost(e) {
  var result = { ok: false, results: [] };
  try {
    var body = JSON.parse(e.postData.contents);
    var token = PropertiesService.getScriptProperties().getProperty('WRITE_TOKEN');
    if (!token || body.token !== token) {
      return _json({ ok: false, error: 'bad token' });
    }
    var dryRun = !!body.dryRun;
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) return _json({ ok: false, error: 'sheet not found: ' + SHEET_NAME });

    var ops = body.ops || [];
    var results = [];
    for (var i = 0; i < ops.length; i++) {
      results.push(_applyOp(sheet, ops[i], dryRun));
    }
    return _json({ ok: true, dryRun: dryRun, results: results });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

function _applyOp(sheet, op, dryRun) {
  if (op.action === 'update') {
    if (!op.row || op.row < DATA_START_ROW) {
      return { action: 'update', ok: false, error: 'invalid row: ' + op.row };
    }
    var written = {};
    for (var col in op.fields) {
      written[col] = op.fields[col];
      if (!dryRun) sheet.getRange(op.row, parseInt(col, 10)).setValue(op.fields[col]);
    }
    return { action: 'update', ok: true, row: op.row, fields: written };
  }
  if (op.action === 'append') {
    var newRow = sheet.getLastRow() + 1;
    if (newRow < DATA_START_ROW) newRow = DATA_START_ROW;
    var written = {};
    for (var col in op.fields) {
      written[col] = op.fields[col];
      if (!dryRun) sheet.getRange(newRow, parseInt(col, 10)).setValue(op.fields[col]);
    }
    return { action: 'append', ok: true, row: newRow, fields: written };
  }
  return { action: op.action, ok: false, error: 'unknown action' };
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Run this once manually from the Apps Script editor to set the shared
 * secret (Run -> setWriteToken -> approve permissions). Change the value
 * below first, then delete it from source after running once. */
function setWriteToken() {
  PropertiesService.getScriptProperties().setProperty('WRITE_TOKEN', 'PASTE-A-LONG-RANDOM-SECRET-HERE');
}
