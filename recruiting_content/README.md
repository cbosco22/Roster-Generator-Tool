# Navy Baseball — Recruiting Graphics Project Handoff

**Program:** United States Naval Academy Baseball
**Purpose:** Single, shareable recruiting graphics for direct outreach to high-school recruits and social posting, modeled on the Navy Football "Official Visit" deck.
**Prepared for:** transitioning production into Claude Code (or a fresh Claude session).

---

## 1. What's been made so far

**Format only produced to date: static graphics.** No captions, video scripts, or motion assets have been created yet — that's open runway. Each graphic is a **1080 × 1350 (4:5 portrait) PNG**, built from a self-contained **HTML/CSS file** and rendered to image. Each is a standalone value-prop ("The Pitch"), not part of a slide deck.

Five graphics are complete, one per recruiting pillar:

| # | Pillar | Headline | Approach |
|---|--------|----------|----------|
| 1 | Money / Degree Value | "An Ivy-Caliber Degree — Free." | Stat-driven. $350K+ → $0 comparison; #3 liberal-arts, #2 PayScale, $131K mid-career; scholarship + $100K/yr service + $36K career-starter loan. |
| 2 | Service | "Choose How You Serve." | Photo tiles. 6 service paths (Aviation, Surface, Submarines, Marines, Special Warfare, Cyber) each with a real photo + label. |
| 3 | Academics | "23 Majors. Chart Your Course." | Stat + list. 3 divisions, popular majors as gold pills (Quant Econ tagged "business & finance path"), careers band. |
| 4 | Life After Service | "Five Years In. Set For Life." | Two-column. "Stay in / retire by 42" vs "Branch out"; alumni ribbon (1 President, 20+ Congress, 54 astronauts). |
| 5 | Baseball | "We Don't Buy Players. We Build Them." | Photo banner + tiles. Development-first pitch: facilities, TrackMan/TruMedia/Aware, fully-loaded staff, lowest portal activity in the country. |

Each graphic ships as **two files**: `Navy_Baseball_<Pillar>.png` (the deliverable) and `Navy_Baseball_<Pillar>.html` (editable source).

**Not yet done:** square (1080×1080) and 16:9 exports; captions; video scripts; any motion/animation.

---

## 2. Brand & style system

### Color palette
```
--navy-0  #06152C   deepest navy (vignette edges, gradient base)
--navy-1  #0B2348   primary navy (background)
--navy-2  #163765   panel / card fill (used at ~26% alpha)
--gold    #C9A85C   primary gold accent
--gold-br #E6CF8B   bright gold (numbers, emphasis)
--cream   #F5F2EA   headline white / body
--steel   #90A6C6   secondary / muted text
```
**Background** is always a layered navy gradient:
```css
background:
  radial-gradient(120% 80% at 16% 0%, #1B3E72 0%, rgba(27,62,114,0) 52%),
  radial-gradient(140% 120% at 100% 100%, #0E2B57 0%, rgba(14,43,87,0) 50%),
  linear-gradient(160deg,#0B2348 0%,#081B38 55%,#06152C 100%);
```
Plus a **halftone dot texture** (`radial-gradient` dots, `mix-blend-mode:overlay`, ~50% opacity) and an **inset vignette** (`box-shadow: inset 0 0 220px 60px rgba(2,9,20,.65)`).

### Typography
| Role | Font | Notes |
|------|------|-------|
| Display headlines | **Anton** | ALL CAPS, `transform: skewX(-7deg)`, line-height ~.85. Two-line headlines: line 1 cream, line 2 gold. |
| Big stat numbers | **Barlow Condensed** (700) | e.g. `$131K`, `#3`, `$350,000+`. |
| Body / labels / eyebrows | **Oswald** | weights 300 (body), 500–600 (labels, letter-spaced caps). |

Fonts are open-source, pulled from the Google Fonts GitHub repo (see §4). The skewed Anton caps are the signature "athletic poster" look.

### Layout template (every graphic shares this skeleton)
1. **Gold corner-bracket frame** inset 34px, with heavier gold L-brackets top-left / bottom-right.
2. **Eyebrow** (top-left): a 3-line gold "wing"/chevron motif + `NAVY BASEBALL · THE PITCH` in letter-spaced gold caps.
3. **N★ "NAVY" academy mark** (top-right), crisp, ~114px tall.
4. **Faint anchor watermark** bleeding off a bottom corner (~6–7% opacity).
5. **Headline** — two skewed Anton lines (white + gold).
6. **Subhead** — one–two lines, Oswald 300, key phrase bolded white.
7. **Body** — varies by pillar: stat ribbons, gold "pill" tags, photo tiles/banners, two-column cards.
8. **Footer** — `NAVY BASEBALL` wordmark (Anton, skewed, "BASEBALL" in gold) + a right-aligned kicker (e.g. *"It's not the next 4 years. It's the next 40."*).

### Logos (official, program-provided)
Three official marks were processed to transparent PNGs and reused everywhere:
- **N★ "NAVY" academy mark** → `nstar.png` (top-right on every graphic)
- **Anchor logo** → `anchor.png` (faint background watermark)
- **"NAVY" wordmark** → `navyword.png` (available; not yet placed)

These are the program's own marks (user-provided) — safe to use freely. Service-branch emblems (USMC Eagle-Globe-Anchor, SEAL Trident) were intentionally **not** reproduced; use official files if provided, otherwise clean silhouettes.

### Subtle Navy motifs
US flag, ships, jets, Marine/SEAL imagery are deployed **contextually and sparingly** — reserved for pillars where they fit (Service, Baseball), never pasted on every graphic. Stat/type-driven pillars (Money, Academics, After Service) stay clean: anchor watermark + N★ mark only.

### Tone of voice
- **Confident, punchy, recruiting-pitch energy.** Short declarative lines. Two-line skewed headlines that land a hook.
- **Stat-forward** — lead with the number, source it.
- **Every claim must be defensible.** Accuracy is non-negotiable (see §6). Unverifiable claims get cut, not softened.
- Recurring device: the long-game frame — *"It's not the next 4 years. It's the next 40."*
- No emojis in the graphics themselves; clean and premium.

---

## 3. Content pillars

The graphics were organized around the program's **five recruiting-pitch pillars** (evergreen value props aimed at a recruit deciding where to play):

1. **School / Academics** — #1 public college, top-5 engineering, 23 majors.
2. **Money / Degree Value** — free + paid, alumni earning potential, service comp, career-starter loan.
3. **Baseball** — Power-4 facilities, player-dev tech, staff, development-first (no portal) identity.
4. **Service** — broadest career options of any academy; each path unique.
5. **Life After Service** — 20-yr pension / retire by 42, or private-sector careers (CEOs, airline captains, senators, a President).

These map into a **recurring "The Pitch" content stream** for an ongoing calendar. Complementary streams to build out for daily cadence: **commits & signings**, **game highlights / recaps**, **player & alumni spotlights**, **USNA life / "a day in the Yard,"** **facility & renovation updates**, and **draft / Cape Cod / pro-pipeline milestones**.

---

## 4. Technical pipeline (for Claude Code)

Everything is **HTML/CSS rendered to PNG** — no design app. Fully reproducible in a code environment.

### Render (Playwright + Chromium, Node)
```js
// render.js  →  node render.js
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 2 });
  await page.goto('file:///path/to/graphic.html');
  await page.waitForTimeout(400);
  await (await page.$('.card')).screenshot({ path: 'out.png' }); // exports 2160×2700 @2x
  await browser.close();
})();
```

### Fonts (install once, then reference by family name)
```bash
mkdir -p ~/.fonts
curl -sL -o ~/.fonts/Anton-Regular.ttf        "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
curl -sL -o ~/.fonts/Oswald.ttf               "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf"
curl -sL -o ~/.fonts/BarlowCondensed-Bold.ttf "https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf"
fc-cache -f
```

### Photo processing (ImageMagick — cover-crop to a target box)
```bash
convert INPUT.JPG -resize {W}x{H}^ -gravity center -extent {W}x{H} -quality 88 out.jpg
# Photo tiles use CSS background-size:cover + a bottom-weighted dark scrim gradient so gold labels stay legible.
```

### Reusable HTML skeleton (paste-ready starting point)
```html
<div class="card">
  <img class="anchor" src="anchor.png">      <!-- faint watermark -->
  <img class="brandmark" src="nstar.png">    <!-- N★ mark, top-right -->
  <div class="frame"></div>                  <!-- gold corner brackets -->
  <div class="wrap">
    <div class="eyebrow"><span class="wing"><i></i><i></i><i></i></span>
      <span class="lbl">Navy Baseball · The Pitch</span></div>
    <div class="head"><h1>
      <div class="l1">Line One</div>          <!-- cream -->
      <div class="l2">Line Two.</div>         <!-- gold -->
    </h1><p class="sub">Subhead with a <b>bolded hook</b>.</p></div>
    <!-- pillar body: stat ribbon / gold pills / photo tiles / two-column cards -->
    <div class="spacer"></div>
    <div class="foot"><div class="mark">Navy <span>Baseball</span></div>
      <div class="meta"><b>Kicker line.</b>Second line.</div></div>
  </div>
</div>
```
Core CSS tokens live in `:root` (see §2). The full CSS for each pillar is in its `.html` source file — copy the closest pillar and swap content.

### File / naming convention
- `Navy_Baseball_<Pillar>.html` — editable source (inline CSS, references local PNGs)
- `Navy_Baseball_<Pillar>.png` — 2160×2700 export
- Shared assets: `nstar.png`, `anchor.png`, `navyword.png`, plus per-graphic photos (`svc_*.jpg`, `bb_*.jpg`, …)

---

## 5. Example outputs

Three representative graphics are attached to show the range of the system:

- **`Navy_Baseball_Degree_Value.png`** — the pure **stat-driven** template (comparison, stat trio, perk row, financial bullets).
- **`Navy_Baseball_Service.png`** — the **photo-tile** template (6 real photos in a grid with scrims + gold labels).
- **`Navy_Baseball_Baseball.png`** — the **photo-banner + tile** template (wide player banner over a 3-photo row over a 2×2 feature grid).

### Sample captions (voice reference — NOT yet produced, drafted here to seed tone)
> **Money/Degree:** "Do the math no one else will show you. A top-3 education in America. $0 tuition. A paycheck while you earn it — and a salary that climbs past six figures. The next 40 years > the next 4. ⚓ #NavyBaseball"

> **Baseball:** "We don't buy players. We build them. No scholarships, no NIL, no portal — every dollar goes into development. TrackMan, TruMedia, a fully-loaded staff, a $5M facility on the way, and the lowest portal activity in the country. #BuiltNotBought"

> **Service:** "Sea. Air. Undersea. Ground. Cyber. Special ops. No academy in America gives you more ways to serve. Choose your path. ⚓ #NavyBaseball"

(Emoji/hashtag usage above is a starting point — captions can run cleaner or hotter to taste.)

---

## 6. Accuracy & guardrails (important)

Factual accuracy is the program's firm priority. Rules that governed this project:

- **Verify current, external stats before publishing.** Rankings, salaries, and cost figures change yearly. Sources used: **U.S. News 2026** (#1 public, #3 liberal-arts, top-5 undergrad engineering), **PayScale** (#2 alumni earning potential, $131K mid-career), **DoD / Blended Retirement System** (40% base pay at 20 yrs, ~$3.5M lifetime value), **usna.edu** (23 majors, three academic divisions), and program-provided figures ($5M renovation, coaching staff, tech).
- **Distinguish program claims from verified facts.** The baseball "lowest transfer-portal activity — in and out — of any school in the country" line is a **program-provided superlative**; confirm it's current each cycle before wide distribution.
- **Career-starter loan:** $36,000 at 0.75% APR (Navy Federal Career Kickoff Loan), available after sophomore year — verified.
- **Service comp** framed as *total pay & allowances* (~$100K/yr over the 5-yr obligation) to stay defensible on base-pay-only scrutiny.
- **No fabricated specifics.** Coaching pedigrees kept general ("highest levels of baseball") until real bios are supplied. Roster-major claims were removed for lack of verifiable data.
- **Audience note:** this targets high-school **recruits** — standard college athletic recruiting. Keep it clean and age-appropriate.

---

## 7. What to hand over / pick up next

**Upload to the new session:** the 5 `.png` deliverables, their 5 `.html` sources, and the shared assets (`nstar.png`, `anchor.png`, `navyword.png`, and the pillar photos).

**Immediate next steps on the roadmap:**
- Square (1080×1080) + 16:9 exports of all five for X / IG feed / stories.
- Caption copy per graphic (voice reference in §5).
- A daily-cadence content calendar organized by pillar + the complementary streams in §3.
- Photos still wanted: indoor cage facility; $5M renovation renderings.
- Optional: motion/video versions and the two remaining logo placements.
