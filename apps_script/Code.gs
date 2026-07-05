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
    // Idempotency (2026-07-02, "the guarantee"): each op carries a content
    // hash (op_id). Applied op_ids are remembered for 6h - a retried or
    // re-imported op that already ran is SKIPPED, so clients may retry any
    // failure blindly without double-appending players. A genuinely edited
    // op (e.g. corrected rating) hashes differently and still applies.
    var cache = CacheService.getScriptCache();
    // Find the last data row ONCE per request and count appends forward
    // from there. The old per-append scan re-read the whole ~4,700-row
    // name column for every appended player - with a 75-player post-event
    // batch that alone blew past the caller's HTTP timeout (2026-07-02).
    var appendCursor = { next: _findLastDataRow(sheet, firstNameCol) + 1 };
    if (appendCursor.next < DATA_START_ROW) appendCursor.next = DATA_START_ROW;
    for (var i = 0; i < ops.length; i++) {
      var op = ops[i];
      var ckey = op.op_id ? ('op_' + op.op_id) : null;
      if (ckey && !dryRun && cache.get(ckey)) {
        results.push({ action: op.action, ok: true, skipped_duplicate: true });
        continue;
      }
      // Per-op isolation (root-fix for the 2026-07-05 Hoover outage): one
      // op throwing used to abort the WHOLE request via doPost's outer
      // catch - everything after it never ran, the client saw a bodyless
      // error, and retries died on the same op forever (earlier ops skip
      // via the op_id cache, then the same throw repeats). Now a throwing
      // op becomes a normal per-op failure result and the loop keeps
      // going, so one bad row can never take the rest of the batch down.
      var res;
      try {
        res = _applyOp(sheet, op, dryRun, firstNameCol, appendCursor);
      } catch (err) {
        res = { action: op.action, ok: false, player: op.player,
                error: 'op threw: ' + String(err) };
      }
      if (res.player === undefined) res.player = op.player;
      if (res.ok && ckey && !dryRun) cache.put(ckey, '1', 21600);
      results.push(res);
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

// (was _setAndVerify: one setValue+flush+read-back per FIELD. Removed
// 2026-07-05 - flushing 15x per player was the original 2026-07-02
// timeout cause only half-fixed, and a single throwing field aborted the
// whole request. _applyOp now writes all of an op's fields with ONE
// flush and still reads every cell back before reporting it applied.)

// Sheets auto-converts a date-looking string (e.g. "7/1/2026", written for
// Date Added) into a real Date value on write. Reading that cell back then
// returns a Date object, and JS's default String(Date) ("Wed Jul 01 2026
// 00:00:00 GMT...") never matches the plain date string we wrote - a false
// "did not verify" failure on data that landed correctly. Format any Date
// back to M/d/yyyy (matching sheet_write.py's today_str()) before comparing.
function _normalizeForCompare(val) {
  if (Object.prototype.toString.call(val) === '[object Date]') {
    var tz = SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetTimeZone();
    return Utilities.formatDate(val, tz, 'M/d/yyyy');
  }
  return String(val);
}

function _applyOp(sheet, op, dryRun, firstNameCol, appendCursor) {
  var targetRow;
  if (op.action === 'update') {
    if (!op.row || op.row < DATA_START_ROW) {
      return { action: 'update', ok: false, error: 'invalid row: ' + op.row };
    }
    targetRow = op.row;
  } else if (op.action === 'append') {
    targetRow = appendCursor.next;
    appendCursor.next += 1;
  } else {
    return { action: op.action, ok: false, error: 'unknown action' };
  }

  var written = {};
  var mismatches = [];
  var fieldErrors = [];
  if (dryRun) {
    for (var dcol in op.fields) written[dcol] = op.fields[dcol];
  } else {
    // Set every field first, flush ONCE, then read everything back.
    // A field whose setValue throws (e.g. a data-validation reject) is
    // recorded and skipped - the op's clean fields still land.
    var pending = [];
    for (var col in op.fields) {
      try {
        sheet.getRange(targetRow, parseInt(col, 10)).setValue(op.fields[col]);
        pending.push(col);
      } catch (err) {
        fieldErrors.push(col + ': ' + String(err));
      }
    }
    try {
      SpreadsheetApp.flush();
    } catch (flushErr) {
      // The batched flush can't say WHICH field it choked on, so redo
      // this op field-by-field with individual flushes (slow, but only
      // ever runs on an already-failing op) to pin the exact offender
      // while every clean field still lands.
      pending = [];
      fieldErrors = [];
      for (var scol in op.fields) {
        try {
          sheet.getRange(targetRow, parseInt(scol, 10)).setValue(op.fields[scol]);
          SpreadsheetApp.flush();
          pending.push(scol);
        } catch (err2) {
          fieldErrors.push(scol + ': ' + String(err2));
        }
      }
    }
    for (var j = 0; j < pending.length; j++) {
      var vcol = pending[j];
      var actual = sheet.getRange(targetRow, parseInt(vcol, 10)).getValue();
      written[vcol] = actual;
      // Loose equality: Sheets can return a Date object for a date string,
      // or a number for a numeric string - normalize both sides before
      // comparing to avoid false-positive mismatches on those, while still
      // catching a value that genuinely did not take.
      if (_normalizeForCompare(actual) !== _normalizeForCompare(op.fields[vcol]) &&
          !(actual === '' && op.fields[vcol] === '')) {
        mismatches.push(vcol);
      }
    }
  }
  var problems = [];
  if (fieldErrors.length) {
    problems.push('These columns threw on write: ' + fieldErrors.join('; '));
  }
  if (mismatches.length) {
    problems.push('These columns did not verify after write: ' + mismatches.join(', '));
  }
  if (problems.length) {
    return { action: op.action, ok: false, row: targetRow, fields: written,
            error: problems.join(' | ') };
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
