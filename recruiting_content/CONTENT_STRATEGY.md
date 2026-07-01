# Navy Baseball Recruiting — Content Strategy

Daily-cadence Instagram/X content plan built on top of the "Navy Baseball Recruiting Kit" handoff (see `README.md` for the full brand system, templates, and pipeline). This file defines the recurring cadence; `calendar/` holds dated, filled-in schedules.

---

## 1. Weekly rhythm (5x/week, weekdays)

Weekends are not scheduled — treat them as **opportunistic**: if coaches are at a live event (tournament, showcase) on a Saturday/Sunday, capture photos/video and post reactively. Don't force a weekend slot with no real content behind it.

| Day | Stream | Purpose |
|-----|--------|---------|
| Monday | **The Pitch** | Rotate the 5 evergreen recruiting-pillar graphics (Academics, Money/Degree Value, Baseball, Service, Life After Service). Already fully produced — see `exports/`. |
| Tuesday | **Player / Alumni Spotlight** | One recruit/commit or one alum (pro-pipeline or notable post-service career), photo + short bio. |
| Wednesday | **USNA Life** | "A day in the Yard" — candid, human content: formation, Bancroft Hall, campus, team downtime. Lower-production, phone-photo-friendly. |
| Thursday | **Facility / Recruiting Trail** | Alternates between program/facility updates (renovation progress, new tech) and behind-the-scenes from whatever event coaches are actually working that week. |
| Friday | **Commits & Signings / Pro-Pipeline** | Reactive slot — real commit announcements, signings, draft news, Cape Cod League placements. Only runs when there's real news; don't manufacture one. |

This is a 5-post/week cadence, not literal daily — sustainable and realistic given most streams depend on real, sourced material (guardrail below).

---

## 2. Streams in more detail

1. **The Pitch** — the 5 pillar graphics already built (`source/`, `exports/`). Fully evergreen, can be reposted/rotated indefinitely, works for both new-recruit outreach and general feed content.
2. **Commits & Signings** — reactive news content, one graphic/post per real commit or signing.
3. **Game Highlights / Recaps** — in-season only (Feb–June); dormant during summer travel-ball season.
4. **Player & Alumni Spotlights** — recruit features, and alumni in the pro pipeline or notable post-service careers.
5. **USNA Life** — culture/lifestyle content, humanizes the program beyond the recruiting pitch.
6. **Facility & Renovation Updates** — the $5M facility renovation, tech (TrackMan/TruMedia/Aware), any physical program upgrades.
7. **Draft / Cape Cod / Pro-Pipeline Milestones** — draft day, summer-league placements, pro call-ups.

Streams 2, 4, 6, 7 are **input-dependent** — they need real names, photos, or news from Chris/the program. Nothing in this plan fabricates a commit, a player name, or a stat. Anywhere the calendar can't be filled with sourced material, it's flagged, not guessed (per the accuracy rule below).

---

## 3. Production pipeline

Unchanged from the original handoff — see `README.md` §4 for full detail:

- HTML/CSS source → Playwright/Chromium render → PNG (`source/render.js`, `source/setup.sh`)
- Brand tokens (colors, type, layout skeleton) live in each `.html`'s `:root` — copy the closest existing pillar file and swap content for new graphics.
- Photos are cover-cropped with ImageMagick to fit tile/banner boxes.

**Not yet done, still open from the original roadmap:**
- Square (1080×1080) and 16:9 exports of the 5 existing graphics (for IG/X format flexibility)
- Motion/video versions

---

## 4. Accuracy guardrails (carried over from the original kit — non-negotiable)

- No fabricated names, stats, or commits. If a spotlight, event, or news item isn't confirmed, the calendar slot is marked **Needs Input**, not filled with a placeholder.
- Rankings/salary/cost figures must be re-verified before reuse if more than ~1 year old.
- Program superlatives (e.g. "lowest transfer-portal activity in the country") get re-confirmed each cycle before wide distribution.
- Audience is high-school recruits — keep it clean and age-appropriate.

---

## 5. Open inputs needed from Chris (unlocks the flagged calendar slots)

- [ ] Player commit/spotlight candidates — name, one-line bio, headshot or action photo (ongoing, weekly)
- [ ] Alumni spotlight candidates — pro-pipeline placements or notable post-service careers, + photo
- [ ] USNA "day in the Yard" photo library — candid team/campus shots (phone photos are fine)
- [ ] July/August recruiting event schedule — which showcases coaches are attending and when, for Recruiting Trail posts
- [ ] Indoor cage facility photos + $5M renovation renderings (also flagged in the original README as still wanted)
- [ ] Real-time heads-up on commits/signings as they happen, for the Friday reactive slot

---

## 6. Platform notes

- The 5 existing graphics are 4:5 (1080×1350) — native IG feed format, and posts fine to X as-is. Square/16:9 crops (open item above) would add Stories/X-banner flexibility but aren't required to start posting.
- Same asset can run on both Instagram and X; captions may need light trimming for X's shorter effective read length.
