# Navy Recruiting — Field Tool

A mobile-friendly web app for coaches in the field. Snap a photo of any
tournament team's printed roster → get back a Navy-formatted PDF + an
on-screen summary of which players are on Navy's recruiting board or
PBR-ranked.

Pipeline: **photo → Claude vision → roster JSON → DB + PBR match → Navy PDF**

---

## What it does (coach view)

1. Open the app URL on a phone (works in Safari/Chrome, no install needed).
2. Tap **Field Tool**.
3. Take a photo of the roster or upload one.
4. Type the event name (e.g. `PG WWBA 17U Championship`) and pick the age division.
5. Tap **Generate PDF**.
6. Read the on-screen summary (DB hits, PBR ranks) → tap **Download PDF** for the full Navy-formatted output.

Time: ~10–20 seconds per roster (vision call + PDF render).

---

## What it does (admin view)

The **Admin** tab shows current data status and lets Chris swap in:
- A new `Navy_Recruiting_Sheet.xlsx`
- A fresh set of PBR ranking JSONs → rebuilds `data/pbr_rankings.pkl`

> **Important about persistence on Streamlit Cloud:** the container's filesystem
> resets on restart (or after ~30 min of inactivity → sleep → wake). Admin
> uploads work for the current session, but for **permanent** updates also
> commit the new file to `data/` in your GitHub repo. The Admin tab provides
> a download button for the rebuilt pkl so you can drag-and-drop it into
> GitHub's web UI.

---

## One-time setup

### 1. Get an Anthropic API key
- Go to https://console.anthropic.com → API keys → Create.
- Each photo extraction costs ~$0.01 with Claude Sonnet 4.6.

### 2. Push this folder to a GitHub repo
```
field_tool/
├── app.py
├── photo_to_roster.py
├── gen_roster_pdf.py
├── db_loader.py
├── fetch_db.py
├── org_tier.py
├── travel_programs.json
├── build_rankings.py
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/secrets.toml.example
└── data/
    ├── recruiting.xlsx          ← drop your current xlsx here
    └── pbr_rankings.pkl         ← built once with build_rankings.py
```

### 3. Build the initial PBR pkl
```bash
python build_rankings.py data/pbr_rankings.pkl \
  PBR_Rankings_2027_2028_National_Rankings.json \
  PBR_Rankings_2027_2028_2026-05-23_State*.json
```

### 4. Deploy to Streamlit Community Cloud
- Sign in at https://share.streamlit.io with GitHub.
- Click **New app**, pick the repo, main branch, `app.py`.
- Click **Advanced settings → Secrets** and paste:
  ```toml
  ANTHROPIC_API_KEY = "sk-ant-..."
  ```
- Click **Deploy**. You'll get a public URL like `navy-field-tool.streamlit.app`.

Share that URL with the staff. Bookmark it on each iPhone's home screen.

---

## Run locally (dev)

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit secrets.toml to add your real key
streamlit run app.py
```

---

## Updating data

| What changed | Where | Sticks? |
|---|---|---|
| Recruiting xlsx | Admin tab → upload | Current session only |
| Recruiting xlsx (permanent) | Commit `data/recruiting.xlsx` to GitHub | ✓ persistent |
| PBR rankings (mid-summer drop) | Admin tab → upload JSONs → download new pkl → commit `data/pbr_rankings.pkl` to GitHub | ✓ persistent |

Streamlit Cloud auto-redeploys on every push to the branch — ~30 sec.

---

## Architecture

```
[photo] → photo_to_roster.extract_roster_from_image() ─┐
                                                       ├─ {team_name, players[]}
                                                       │
[xlsx]  → db_loader.parse_xlsx() ────────────────────┐ │
                                                     ├─┤
[pkl]   → gen_roster_pdf loads PBR rankings ─────────┘ │
                                                       ▼
                       gen_roster_pdf.build_pdf() → Navy-formatted PDF
```

All the locked logic (PDF format, name matching, PBR cross-validation) is in
the existing scripts — the app is a thin Streamlit wrapper.

---

## Cost ballpark

Claude Sonnet 4.6 vision is roughly $0.003 input + $0.015 output per million
tokens. A roster photo is ~2k input tokens + ~1k output → about **$0.01–0.02 per photo**.
A full tournament weekend (~40 teams × all 3 coaches) is under $5.

## Troubleshooting

- **"Couldn't read any players"** — photo is too dark, angled, or low-res. Take a flat, well-lit shot and try again.
- **DB hits look wrong** — the xlsx in `data/` may be stale. Update via Admin tab.
- **PBR ranks blank for known ranked player** — verify `data/pbr_rankings.pkl` is present and recent; rebuild via Admin tab if needed.
- **App keeps sleeping** — Streamlit Cloud free tier sleeps after ~30 min inactivity. First request after sleep takes ~20 sec to wake. Upgrade to paid tier or use a keepalive ping if this is a problem.
