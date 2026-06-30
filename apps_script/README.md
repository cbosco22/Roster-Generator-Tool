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
