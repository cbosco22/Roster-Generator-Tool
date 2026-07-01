# Sheet write endpoint — deployment steps

This is a one-time setup, done by Chris (not from this repo's CI/deploy —
Apps Script lives inside the Google Sheet itself).

1. Open **Recruiting Sheet 2.0** in your browser.
2. **Extensions → Apps Script**. A new tab opens with an empty `Code.gs`.
3. Delete whatever's in the default editor, paste in the full contents of
   `Code.gs` from this folder.
4. Generate a long random secret (e.g. run `python3 -c "import secrets;
   print(secrets.token_urlsafe(32))"` in a terminal, or use any password
   generator). Paste it into the `setWriteToken()` function at the bottom,
   replacing `PASTE-A-LONG-RANDOM-SECRET-HERE`.
5. In the Apps Script editor toolbar, select the `setWriteToken` function
   from the dropdown (next to the Run/Debug buttons), then click **Run**.
   Google will ask you to authorize the script the first time — approve it
   (it's your own script, running with your own Google account).
6. **Delete the real secret value** out of `setWriteToken()` afterward and
   save — it's already stored in the script's properties, no need to leave
   it in the source.
7. **Deploy → New deployment** → gear icon → type **Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone** (this is what lets the app POST to it
     without its own Google login — the shared secret in step 4 is what
     actually protects it, not the access setting)
8. Click **Deploy**, authorize again if asked, then copy the **Web app URL**
   it gives you (looks like `https://script.google.com/macros/s/.../exec`).
9. Give me (or paste into Streamlit Cloud secrets yourself, same rule as
   before — I don't enter credentials into forms) two values:
   - `sheet_write_url` = the Web app URL from step 8
   - `sheet_write_token` = the same secret you set in step 4

That's it — no GCP project, no service account, no OAuth consent screen.

## One-time fix: extend the Filter range

The High School Players tab's native Filter is currently hardcoded to
`$A$3:$AK$1980` — confirmed 2026-06-30 that this already excludes the very
last real player row (1981), and every future appended row makes it worse.
This is exactly why rows added via AppSheet "fall out of the filter."

Before relying on the new write path: open High School Players → click the
filter icon → **Data → Filters → adjust range** → extend it generously past
current data (e.g. to row 5000) so new rows land inside it automatically.
This is a one-time manual fix, not something Code.gs manages dynamically
(safer — it won't fight with a filter you have open or have customized).

## One-time fix: flatten the ID/Name/Pos Group formulas

Columns C ("ID"), D ("Name"), and E ("Pos Group") on High School Players
are live spilling array formulas, not real data. Confirmed 2026-06-30 the
hard way: the first real write (row 1982) got corrupted because the live
formula reacted to new data in column D and re-derived a second label on
top of what the write path had already written there.

The write path (`sheet_write.py`) now computes and writes all three of
these columns itself as plain values, on every write it makes — so this
only matters for the ~1980 rows that predate the write path. One-time
manual fix: select columns **C:E** across all existing data rows, copy
(Cmd+C), then paste special → **values only** (Cmd+Shift+V) onto that same
range. This freezes whatever's currently displayed as plain text and
removes the live formulas for good — nothing about what you see changes,
only how it's produced.

Row 1982 specifically has bad data from before this fix (a corrupted ID
label, and it's missing Date Added / By, which the write path did not set
until this same fix). Needs a manual correction pass after the C:E
flatten — ask me to do it once you've confirmed the flatten is done, since
I can write the corrected values through the same write path.

## Re-deploying after editing Code.gs

If `Code.gs` changes in this repo in the future, the live script needs the
update pasted in manually too (Apps Script isn't auto-synced from git).
After pasting the new version: **Deploy → Manage deployments → edit (pencil
icon) → New version → Deploy**. The URL stays the same, no need to update
Streamlit secrets again unless you create a whole new deployment.

## Testing safely before trusting it

Every write request can include `"dryRun": true` in the JSON body — the
script validates everything (token, row numbers, sheet name) and reports
back exactly what it *would* write, without touching any cells. The Python
side defaults to dry-run until explicitly told not to — see `sheet_write.py`.

**This is not just a suggestion — it caught a real bug 2026-06-30.** A dry
run of the append path came back targeting row 5001, because extending the
Filter range (previous section) made `sheet.getLastRow()` think row 5000
had content, even though real data ends around row 1980. Fixed in `Code.gs`
(scans the actual First Name column for the real last data row instead of
trusting `getLastRow()`), but that fix needs to be **re-pasted and
re-deployed** the same way as step 3+7 above (paste the updated file, then
Deploy → Manage deployments → edit → New version → Deploy) before any real
write is safe to run. Always re-run a dry run after any Code.gs update and
actually read the row numbers in the response before trusting it.
