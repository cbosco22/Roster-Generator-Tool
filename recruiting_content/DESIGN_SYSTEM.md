# Feed Design System — v2 (July 2026 rework)

Chris's feedback (2026-07-03): the first 19 graphics all share one skeleton — navy gradient, gold corner frame, skewed headline, stat columns, chevron bullets, footer — "same graphic with different words and pictures." This doc defines the fix: a small set of **locked constants** plus **six rotating layout archetypes**, so the feed reads as one brand with real variety (the way NFL/college creative departments do it).

## Locked constants (every post, no exceptions)
- Palette: navy `#06152C/#0B2348`, gold `#C9A85C/#E6CF8B`, cream `#F5F2EA`, steel `#90A6C6`
- Type: Anton (skewed headlines), Barlow Condensed 700 (numbers), Oswald (everything else)
- The N-star mark appears once somewhere on every card (`nstar_markonly.png` — star+N crop, no NAVY wordmark)
- "NAVY BASEBALL" wordmark somewhere small
- 1080×1350, rendered @2x via `source/render.js`

## Rotating archetypes

| # | Name | Look | Use for | Prototype / example |
|---|------|------|---------|---------------------|
| 1 | **Statement** | Cream/light background, one giant numeral or 2-word phrase, huge negative space, navy band footer | Single-stat brags ($0, 131, #1) | `Navy_Baseball_Money_Zero.html` |
| 2 | **Cover Story** | Full-bleed photo, navy wash + bottom grade, big headline over photo, editorial vertical spine, no corner frame | Anything with a strong photo (facility, team, town) | `Navy_Baseball_Coaches_Work_v2.html` |
| 3 | **Gold Standard** | Solid gold card, navy ink, ghost numeral bleeding off-edge | Rare, biggest brags only (~1 in 8 posts max) | `Navy_Baseball_Patriot_League_v2.html` |
| 4 | **Data Card** | Dark navy, left gold rail (no corner frame), giant numeral + real data furniture (timeline, chart, list) | Multi-fact stories, paths, timelines | `Navy_Baseball_LifeAfter_RetireBy42_v2.html` |
| 5 | **Split Portrait** | Existing photo-split layout — text column + full-height portrait | People (coaches, alumni, player spotlights) | `Navy_Baseball_Coach_Ristano.html`, `Navy_Baseball_Alumni_Noah_Song.html` |
| 6 | **The Sheet** | The original dense framed card (corner frame, stats, perks) | Sparingly — dense reference posts (draft list, majors overview), ~1 in 6 | `Navy_Baseball_Program_History.html` |

## Feed rhythm rules
- Never two of the same archetype back-to-back
- Alternate dark / photo / light so the profile grid checkerboards
- Gold Standard is a spice, not a staple
- Photos: prefer full-bleed (archetype 2) over inset thumbnails; real photos > decoration
- Every archetype can carry the same caption voice — captions don't change

## Research grounding
Cohesive-but-varied feeds lock constants (palette, type, one mark) and rotate layout archetypes; checkerboard/alternating light-dark rhythm; bold type organized in negative space; gradients on brand palette. Sources: [Content Stadium sports template teardowns](https://www.contentstadium.com/blog/sports-social-media-templates/), [ScoreVision 2025-26 sports design trends](https://blog.scorevision.com/top-4-trends-for-sports-graphics-2025-2026), [SVG sports design trends](https://www.sportsvideo.org/2024/04/02/whats-next-in-sports-graphics-design-creative-trends-shaping-the-industry/), [Instagram grid systems](https://www.postquick.ai/blog/how-to-plan-your-instagram-grid-for-a-brand-templates-examples), [later.com grid cohesion](https://later.com/blog/instagram-grid/).

## Status
- 2026-07-03: Chris approved all four directions. Full rollout done the same day — every unposted queue item restyled across archetypes 1–5, and the 13-item Monday "Pitch" backlog built new in the system (see POSTING_QUEUE.md days 24+). Already-posted launch items stay as-is; the feed evolving forward is normal.
- Source files: v2 restyles live alongside originals as `*_v2.html`; exports always carry the canonical (non-v2) name.
