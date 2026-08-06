# dodworldseries.com — full rework, in the KTP visual language

Companion to `prototype.html` (self-contained, open in any browser; the dashed tan box
bottom-right is a **mockup-only** publication switcher demonstrating the stats gate — it is
not part of the design). The prototype was rendered and interaction-tested in Chrome at
desktop width: day switch, map filter, row detail, show-all, and the published/unpublished
gate all verified working; zero console errors; no horizontal body scroll.

Style source of record: `KTPInfrastructure/sites/support-web/app/templates/index.html`
(the live KTP look — itself derived from `KTPAntiCheat/docs/bundles-web/styles.css`, then
re-paletted to the WSDoD olive scheme; see support-web `design/DESIGN.md` § "Palette change
— WSDoD olive"). Tokens, type scale, spacing scale, panel/pill/table/details components are
**copied, not reinterpreted**. There is a pleasing circularity here: support.ktpdod.com took
its palette *from* WSDoD, so WSDoD adopting the property style is mostly a homecoming.

---

## 1. Recommendations up front

1. **This is a replacement, not a restyle.** The cream-paper field-manual dossier and the
   olive-drab property style are opposite treatments; blending them produces neither. The
   dossier's *voice* survives in small doses (section meta lines like "the order of battle",
   the crest); its *costume* — paper grain, stamps, binding holes, fold creases, Google
   Fonts — does not.
2. **The site is now post-event.** The LAN ran 31 Jul – 2 Aug; the prototype is designed
   around what the site must do *now*: carry the record (teams, results, stats, demos) and
   stay useful as an archive. The pre-event lifecycle (registration CTAs, "TRANSMISSION
   PENDING" stubs) is a next-LAN concern — see §8 open questions.
3. **Stats are the centerpiece and the per-day split is structural.** Two boards, one per
   day, each carrying its own field baseline. There is no DOM state in which Saturday and
   Sunday rows share a table — the incomparability of KTPR across days is enforced by the
   page's shape, not by a footnote (the footnote exists too).
4. **The publication gate must leave no scar.** With `lan_stats_publication.published=0`,
   the Stats section and its nav link are absent and the page reads complete: Results still
   carries the match log, the hero still carries the event facts. In production this is
   server-side (unpublished stats ship **no markup**); the prototype's toggle demonstrates
   both states client-side.
5. **Publish nothing you cannot attribute.** Match *scores* exist in the engine record but
   are not attributed to teams anywhere in the dataset — so the Results section ships the
   verifiable match log (map, time, length, halves, demos) and holds bracket placements
   behind a "being compiled by staff" note rather than guessing. Same discipline as the rest
   of the property: identity is the verified record, never the banner.

---

## 2. Information architecture

```
dodworldseries.com
│
├── Header (STATIC — property requirement)
│     brand "WSDoD — World Series of DoD" · Event · Teams · Results · Stats* · Rules ·
│     Archive · "part of KTP" pill → ktpdod.com          (*absent when stats unpublished)
│
├── Hero — identity + the crest (the page's one pictorial element)
│     eyebrow: Philadelphia · dates · venue · Discord pill
│     event fact tiles: 12-cap/11 registered · 61 players · 100 matches ·
│                       58 tournament · 242 HLTV demos
│
├── § The weekend        — three day cards (draft / groups / playoffs+finals),
│                          venue panel (condensed travel), "how it ran" (KTP stack)
├── § Teams              — 11 registered companies, captain marked, registration date;
│                          honest caption: rosters are as-registered, day-of shifted
├── § Results            — bracket-pending note-box + per-day match logs (31 + 27 rows,
│                          from the engine's own match index)
├── § Player stats       — [gated] two day boards; see §5
├── § Rules              — two <details> panels: Rules of engagement (abridged),
│                          Code of conduct (condensed)
├── § LAN command        — 10 staff cards + recusal note in the section meta
├── § Archive            — Demos panel (242 HLTV + POV filing) · Broadcast panel (casters)
└── Footer               — what this is · Discord · KTP link
```

No JS is required for anything except the stats boards (render, day/map switch, row
detail), which degrade to an empty table without JS — acceptable for a prototype; the
production build should render the default board server-side (see §7).

## 3. Token mapping

All tokens verbatim from `support-web/app/templates/index.html` — **zero new tokens, zero
changed values**: `--bg #171c0a`, `--panel #252a14`, `--panel-2 #323920`, `--inset #101407`,
`--border #3d432b`, `--rule rgba(61,67,43,.5)`, `--text #eae7d4`, `--dim #b6b299`,
`--faint #98947c`, `--red #d0513b` / `--red-soft #e07a63`, `--blue #819746` /
`--blue-soft #9fb45c` (moss — the token name keeps its blue-era spelling, same as the
source), `--amber #c08b5c`, radius 14px, the same panel gradient, the same mono stack
(JetBrains Mono → system mono fallback; the prototype makes no external requests).

Spacing (4/8/12/16/24/32/48, sections on the 48px rhythm) and the type scale
(0.68/0.72/0.78/0.82/0.86/0.92/1.05/1.3 + clamp h1) are the support site's scales.

**Colour discipline carried over:** rust = accent word, brand mark, captain tag, top-3
rank, note-box rail; moss = links, actions, ok, the eyebrow/section dash, KTPR bars, active
tab/chip; tan = the mockup switcher only (deliberately loud, not part of the design);
everything else is the warm-grey ramp. The four position pills are deliberately **neutral**
(border + dim text): Rifle/Heavy/3rd/Sniper are categories, not statuses, and giving them
status colours would spend the semantic palette on decoration.

Components reused verbatim: `.eyebrow` (+ its dash as the section marker — the property's
signature), `.panel/.head/.body`, `.pill`, `.note-box`, `.hint/.prose/.fineprint`,
`details.panel` disclosure, `.scrollbox`, table treatment (th/td rules from `.opstable`),
`.btn/.btn.ghost`, footer, and the `.mock` switcher pattern from the support prototype.

Page-specific components (documented in the stylesheet header): `.crest`, `.statstrip`,
`.daytab`, `.baseline`, `.mapchips/.chip`, `.leader` (+ `.ktprbar`, `.rolepill`,
`.detailbtn`, `.detailgrid`), `.teamgrid/.roster`, `.logtable`, `.staffgrid`. All are built
from the existing scales; none introduce a colour or size outside them.

**The one aesthetic risk:** the dossier's divisional patch, redrawn as an inline SVG in the
property palette (moss crossed rifle-and-bat, bone rim text, rust "★ LAN ★"). It is the
only pictorial element on the page and the only survivor of the field-manual costume —
kept because it is the event's *brand*, not the old page's *treatment*. It hides below
760px rather than compressing.

## 4. Kept / dropped from the current page

**Kept (re-dressed):** event identity and dates; venue + condensed transit facts; the full
team registry with captains and registration dates; rules of engagement (abridged, with the
"original wording governs" fineprint — that caveat is load-bearing and survives); code of
conduct (condensed); staff roster with the recusal note; casters; Discord link; the
POV-demo/HLTV recording facts (now stated as record, not instruction).

**Dropped, with reasons:**
- *Paper costume* — grain, stamps, folds, binding holes, typewriter/serif/stencil Google
  Fonts, load animations. Opposite treatment; also violates the zero-external-requests rule.
- *Registration CTAs + vacancy banner* (player/team Google Forms) — the event is over.
  The form URLs are preserved here for the next cycle:
  players `https://forms.gle/v7iHjA9fV1V6vpTW6`, teams `https://forms.gle/er1VPETNHiXmAHWZ7`.
- *Fee/payment lines* ($160/$50, "deposit fronted by las1k64") — transacted; las1k64's
  fronting is acknowledged nowhere now, which may be worth a thank-you line somewhere if the
  operator cares (flagged, not decided).
- *The schematic venue map (SVG "FIG. 1")* — decorative; the address + transit lines carry
  the same information.
- *"TRANSMISSION PENDING" schedule stub* — replaced by the real match log.
- *Demo submission instructions* (§X filing rules, flash-drive handoff) — instructions to
  attendees during the event; the archive section states what was recorded instead.
- *Masthead doc-ids* ("WSDoD/LAN-26/OPORD-1", "Compiled at hq.dodworldseries", stamp
  numbers) — dossier props. **One flagged unknown:** if "hq.dodworldseries" refers to a real
  build host naming convention someone depends on, it should live in ops docs, not page
  chrome; I could not determine a real purpose, so it was dropped rather than carried.
- *"FILED 14 MAY 2026" chapter stamps and revision line* — replaced by nothing; the builder
  can stamp a "last updated" into the footer if wanted (open question).

## 5. The stats section

### Per-day incomparability — structural, three ways

1. **Two boards, one per day.** The day switch swaps the *entire* board: baseline strip,
   map chips (Saturday has 6 maps, Sunday 7 — the chip row itself changes), and table. No
   view merges days; no control sorts across them, because no such DOM state exists.
2. **The baseline travels with the board.** Each day's field averages (avg K/D,
   kills/half, flags/half, pool) render in a strip *above the table it governs*, captioned
   "KTPR normalizes every player below against these numbers — and only these." The
   normalization basis is visible, not implied.
3. **The day tab faces say it**: "rated against Saturday's field" / "rated against
   Sunday's field" — on the control itself, before the note-box is even read.

The note-box states the rule in words ("A Saturday 1.20 and a Sunday 1.20 are not the same
number") — but it is the *fourth* line of defense, not the first.

Per-map tables reuse **that day's** averages (as the dataset does), so map views stay
comparable within a day and the same three defenses apply unchanged.

### What leads, what is disclosure (~27 fields → 10 columns)

**Leads** (the leaderboard): rank · player · position pill · KTPR (number + bar scaled to
the day's leader) · K–D · K/D · kills/half · flags/half · assists · damage. These are the
three KTPR terms, the two most-asked raw numbers, and the two headline HUD stats. Top 15
rows by default; "Show all 61" expands.

**Progressive disclosure** (per-row "detail" expander, three columns):
- *Where the hits landed* — hitbox distribution as labeled bars (hits + damage each).
- *Class spawns* — the league-vernacular class names (Scharf, Unter, Tommy…) with counts,
  plus the position provenance line.
- *The rest of the ledger* — headshot kills, hits landed, headshot hits, HUD flag caps,
  cap denials, objective score, best streak, grenade/gun kills, prone transitions.

**Deliberately not shown anywhere:** `damage_hlstatsx` (two damage numbers with an ~11%
definitional gap invite the wrong question; the HUD number is shown because it pairs with
hits/hitboxes from the same source), `steam_id` (an identity key, not a stat), `halves`
(implied by matches; kept in the data for tooltips if ever wanted).

**Positions:** the four league positions render as pills — **solid border = declared on
roster, dashed = inferred from Axis class**, with a title tooltip explaining which. The
inference caveat from `lookups.py` (Allied Garand can't distinguish a 3rd from a Rifle) is
exactly why provenance is drawn, not footnoted.

### Publication gate

`body[data-stats="off"]` hides the section and its nav link (prototype). Production must
do this server-side: when `lan_stats_publication.published=0`, the template emits neither
the section nor the nav item nor the JSON — an unpublished dataset should not be one
view-source away. Everything else on the page is written to stand without it: Results
carries the match log, the hero tiles are event facts (match/demo counts), and no copy
elsewhere references "the stats below".

## 6. Real data in the prototype (sources)

- **Players/maps/averages:** `lan-stats/lan-stats.json`, embedded trimmed+minified
  (~134 KB) in a `<script type="application/json">` block. All 61 players × 2 days, all 13
  day-map tables, real names, real KTPR — nothing invented. ⚠️ The dataset was regenerated
  by a concurrent session *while this prototype was being built* (roster-declared roles
  went 3 → 6); the embedded copy is the **2026-08-06 17:32** build. If `build_stats.py`
  runs again, the embedded blob is stale until re-injected — production should template it
  in at render time, not hand-paste.
- **Match logs:** `KTPAntiCheat/docs/reviews/lan-match_index-2026-08-06.csv`, `.ktp` rows
  only — 31 Saturday + 27 Sunday, with start time, map, length, halves, demo counts.
- **Event facts:** same CSV — 100 matches total (58 ktp / 21 scrim / 16 draft / 5 12man),
  242 demo files, Friday = 16 draft + 15 scrims, ~40h of tournament server time.
- **Teams:** `sample.csv` (the registration sheet snapshot the current page renders from),
  all 11 rows, captains = player 1.
- **Rules/conduct/staff/casters/venue:** the current `index.html`.

## 7. Production notes (when this goes real)

- `builder.py` grows three inputs: the registration CSV it already fetches, the match
  index (or a query against `hlstatsx_lan`), and `lan-stats.json` + the publication flag.
  Render server-side with Jinja like today; the stats JSON should be templated into the
  page (or fetched from a same-origin static file) so a dataset rebuild republises without
  hand-editing.
- Self-host JetBrains Mono woff2 same-origin, exactly as bundles-web does — the prototype
  rides the fallback stack by design. Re-check the leaderboard column widths when the real
  face lands.
- The leaderboard's default board should be server-rendered so the page is not
  JS-dependent for its centerpiece; the day/map switching can stay client-side.
- Wide tables already sit in `.scrollbox`; body never scrolls horizontally (verified at
  desktop; **narrow-width QA is pending** — the browser used for verification refused
  window resize, so the 640/760/860px breakpoints are code-reviewed but not eyeballed.
  They are the support site's own patterns).

## 8. Open questions for the operator

1. **Final placements & bracket.** Team-attributed results exist nowhere in the data (the
   match index has scores but not team identities). Who compiles the bracket/placements,
   and in what form? A tiny JSON (`results.json`: round, teams, score, match_ids) would
   slot straight into the pending panel.
2. **Played rosters.** Registration rosters are visibly stale — tags in the stats data
   ([bb], ßℓυ†н, JTM…) don't all match the sheet, and roughly ten tags actually played
   against eleven registered teams. Publish as-registered (current design, with the honest
   caption), or supply a played-roster pass? If the latter: same override-file pattern as
   `team_overrides.json`.
3. **Do player names link anywhere?** profiles.ktpdod.com exists; linking stats rows to
   profiles would knit the property together, but LAN aliases ≠ profile identities and the
   join key would be SteamID — which this design deliberately doesn't render. Decide
   whether the production JSON should carry an opt-in profile URL per player instead.
4. **Demo archive URL.** 242 demos exist; where do they publish for the public? The
   archive panel currently points only at the league archive.
5. **KTPR column sorting.** The boards default to KTPR order and offer no re-sorting.
   Within a single day's board, sortable columns would be safe (the day boundary is
   structural, so sorting can't cross it) — wanted, or is one canonical order better?
6. **The pre-event lifecycle.** Should this template also serve LAN 2027 pre-event
   (registration open, schedule pending)? The section skeleton supports it (Results and
   Stats absent, a registration panel returns), but the copy in the prototype is written
   post-event. Decide before reusing.
7. **las1k64's deposit acknowledgment** — dropped with the fee lines; restore a thanks
   line somewhere if wanted.
8. **A "last updated" stamp** — the dossier's revision line was dropped; the builder can
   stamp the footer if freshness matters post-event.
9. **Crest artwork.** The patch was redrawn in the property palette from the dossier SVG.
   If WSDoD has (or wants) a canonical logo, it replaces the inline SVG one-for-one.
