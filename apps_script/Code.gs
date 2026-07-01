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
 * Column numbers are NEVER hardcoded here (or on the Python side that calls
 * this). Confirmed 2026-06-30: Chris deleted two leading columns on the live
 * sheet, and every hardcoded column number silently pointed at the wrong
 * field - this script reported "ok: true" for every write while most of the
 * data never actually showed up anywhere in the row. Column numbers now come
 * from the request itself (Python resolves them fresh from the live header
 * via db_loader.find_columns() right before every write).
 *
 * This script also no longer trusts setValue() not throwing as proof a
 * write actually stuck. Confirmed the same day: setValue() can report
 * success while the write does not persist (most likely because the sheet
 * was being structurally edited - columns deleted - at the same moment).
 * Every write now flushes and reads the cell back before being reported as
 * applied.
 */

var SHEET_NAME = 'High School Players';
var DATA_START_ROW = 4;
var HEADER_ROW = 3;

function doPost(e) {
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

    var firstNameCol = _findHeaderColumn(sheet, 'First Name');
    if (!firstNameCol) {
      return _json({ ok: false, error: 'Could not find a "First Name" column in row ' +
                    HEADER_ROW + ' - sheet header may have changed.' });
    }

    var ops = body.ops || [];
    var results = [];
    for (var i = 0; i < ops.length; i++) {
      results.push(_applyOp(sheet, ops[i], dryRun, firstNameCol));
    }
    var allOk = results.every(function(r) { return r.ok; });
    return _json({ ok: allOk, dryRun: dryRun, results: results });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

// Finds a column by its exact header text in HEADER_ROW, instead of a
// hardcoded number - see file header comment for why this matters.
function _findHeaderColumn(sheet, label) {
  var lastCol = sheet.getLastColumn();
  var headers = sheet.getRange(HEADER_ROW, 1, 1, lastCol).getValues()[0];
  for (var c = 0; c < headers.length; c++) {
    if (String(headers[c]).trim() === label) return c + 1;
  }
  return null;
}

// sheet.getLastRow() is unreliable here: extending the Filter range (see
// README) or any formatting on empty rows makes Sheets report those rows
// as "having content" even though no player data is there. Scan the real
// First Name column instead.
function _findLastDataRow(sheet, firstNameCol) {
  var maxRow = sheet.getMaxRows();
  var span = maxRow - DATA_START_ROW + 1;
  if (span <= 0) return DATA_START_ROW - 1;
  var values = sheet.getRange(DATA_START_ROW, firstNameCol, span, 1).getValues();
  for (var i = values.length - 1; i >= 0; i--) {
    if (values[i][0] !== '' && values[i][0] !== null) {
      return DATA_START_ROW + i;
    }
  }
  return DATA_START_ROW - 1;
}

// Writes one column's value and reads it back to confirm it actually
// persisted, instead of trusting that setValue() not throwing means the
// write stuck (it does not always - see file header comment). Returns the
// value actually found in the cell afterward.
function _setAndVerify(sheet, row, col, value) {
  var range = sheet.getRange(row, col);
  range.setValue(value);
  SpreadsheetApp.flush();
  return range.getValue();
}

function _applyOp(sheet, op, dryRun, firstNameCol) {
  var targetRow;
  if (op.action === 'update') {
    if (!op.row || op.row < DATA_START_ROW) {
      return { action: 'update', ok: false, error: 'invalid row: ' + op.row };
    }
    targetRow = op.row;
  } else if (op.action === 'append') {
    targetRow = _findLastDataRow(sheet, firstNameCol) + 1;
    if (targetRow < DATA_START_ROW) targetRow = DATA_START_ROW;
  } else {
    return { action: op.action, ok: false, error: 'unknown action' };
  }

  var written = {};
  var mismatches = [];
  for (var col in op.fields) {
    var intended = op.fields[col];
    if (dryRun) {
      written[col] = intended;
    } else {
      var actual = _setAndVerify(sheet, targetRow, parseInt(col, 10), intended);
      written[col] = actual;
      // Loose equality: Sheets can return a Date object for a date string,
      // or a number for a numeric string - compare as strings to avoid
      // false-positive mismatches on those, while still catching a value
      // that genuinely did not take.
      if (String(actual) !== String(intended) && !(actual === '' && intended === '')) {
        mismatches.push(col);
      }
    }
  }
  if (mismatches.length) {
    return { action: op.action, ok: false, row: targetRow, fields: written,
            error: 'These columns did not verify after write: ' + mismatches.join(', ') };
  }
  return { action: op.action, ok: true, row: targetRow, fields: written };
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
