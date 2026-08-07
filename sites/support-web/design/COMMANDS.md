# support.ktpdod.com — command reference research & curation

Companion to `prototype.html` (§ Server commands, § In-game admin commands, § Bot command hub)
and `DESIGN.md`. Every permission claim below was verified against plugin source, not guessed;
file:line references point at the gate itself. Where the source is ambiguous it says so.

**Curation rule (operator, 2026-08-05):** the page is not an inventory. It carries the commands a
player or captain actually types, grouped by task; everything else is deliberately omitted and
recorded here so the gap is never read as an oversight and the raw 54 re-added.

---

## 1. How the inventory was built

54 dot-commands are registered via `register_clcmd("say ...")` across four plugins. Three more
match-start forms are **not** in that list because they take arguments: the engine sends chat as one
quoted token, so `register_clcmd("say .ktp")` can never match `.ktp seasonpass`. Those route through
the generic hook `cmd_say_hook` (`KTPMatchHandler.sma:6583`):

| Command | Handler | Notes |
|---|---|---|
| `.ktp <password>` | `cmd_match_start` via say hook :6643 | Official match. Password required (`is_official_match_type` gate, :6789). Refused outside KTP season (:6779). |
| `.ktpOT <password>` / `.ktpot` | say hook :6621 (case-insensitive) | Official overtime. Password required. |
| `.draftOT <...>` / `.draftot` | say hook :6632 | Draft OT — **no password** (drafts bypass the check). |
| `.setallies <name>` / `.setaxis <name>` | say hook :6658/:6665 → `cmd_setteam` :6331 | Set custom team names; any player, `.ktp`/`.draft` pre-start only. **Not in the raw 54** — argument-bearing. |
| `.setstate <args>` | say hook :6672 → `cmd_setstate` :8131 | **ADMIN_RCON** — post-crash state restore. |

The exact-match `register_clcmd` handlers for `.ktpOT`/`.draftOT` (lines 4094–4109) also exist but
only fire on the bare command with no password; the hook is the path that matters.

## 2. Permission verification (the part that must not be wrong)

| Command | Gate | Source |
|---|---|---|
| `.forcereset` | `ADMIN_RCON` + confirm step | `KTPMatchHandler.sma:7655` |
| `.restarthalf` / `.h2restart` | `ADMIN_RCON` + confirm; live 2nd half only, not OT | `:7904` |
| `.setstate` | `ADMIN_RCON` + retype-confirm (10s, keyed slot+authid) | `:8132` |
| `.override_ready_limits` | **Not a flag** — hardcoded SteamID allowlist `OVERRIDE_ADMIN_SIDS` (`is_override_admin`, :7262). A testing tool, auto-disarmed on every teardown. | `:7292` |
| `.kick` | `ADMIN_KICK` (flag c); immunity (a) honored | `KTPAdminAudit.sma:519` |
| `.ban` / `.unban` | `ADMIN_BAN` (flag d) | `:551`, `:600` |
| `.restart` / `.quit` | `ADMIN_RCON` (flag l) | `:1642`, `:1689` |
| `.changemap` | **No flag — any player.** Deliberate ("encourages map rotation"); blocked during active matches and while a changemap is in flight. | `:1823–1838` |
| `.hltvrestart` | `ADMIN_RCON` (`#define ADMIN_HLTVRESTART ADMIN_RCON`, :95) | `KTPHLTVRecorder.sma:455` |
| All KTPPracticeMode commands | No flag — gated only on practice-mode state (`.prac` refused while a match is active, :361) | `KTPPracticeMode.sma:359–457` |
| Everything else (start/confirm/ready/status/score/tech/resume/go/cancel/names…) | No flag; state-machine + team checks only (e.g. spectators can't `.tech`, only the pause-owning team can `.resume`) | various |

The one **surprise in both directions**: `.changemap` (registered by the *admin* plugin) is public,
and `.setallies`/`.setaxis`/`.setstate` (absent from the raw list) exist. Both are exactly the class
of error the reference exists to prevent.

## 3. Pause system facts used in the copy

- `.pause` / `.tac` / `.tactical` all route to `handle_pause_request`, which unconditionally refuses:
  *"Tactical pauses are disabled. Use .tech"* (`KTPMatchHandler.sma:5760–5766`). The page says this
  in a red callout because players will otherwise try them mid-match.
- Tech budget: **per team per match**, set at match start, carried across the halftime side swap;
  OT seeds its own. (Root `CLAUDE.md` § Pause System; cvar `ktp_tech_budget_seconds`.)
- Unpause ceremony (live): owner `.resume` → other team `.go` → countdown. Non-live pauses unpause
  directly (owner-locked; RCON admins pass — :5787–5793).
- Disconnect auto-pause exists and resumes through the same ceremony — the page mentions the
  behavior in one fineprint line without teaching `.nodc` (see omissions).

## 4. What renders where (tier map)

| Group | Tier | Prototype location |
|---|---|---|
| Match-flow strip (7 steps) | public | § Server commands, top |
| Pause rule callout | public | § Server commands, note-box |
| Starting a match (7 rows) · Ready & status (3) · Pauses (3) · Practice & between matches (5) | public | § Server commands, collapsed `<details>` groups |
| Cvar-kick / FastDL / demos-and-spectating deflection | public | § Report, sidebar ("Before you report") |
| Connect strings | public | copy button per row on the existing status grid |
| Match recovery & server control (7 rows) | **KTP admin only** | § Admin → "In-game admin commands" |
| Booking guidance (core placement) | **KTP admin only** | § Admin → "Booking a server" |
| Bot hub `/ops` · `/ac` · `/ktp` | **KTP admin only** | § Admin → "Bot command hub" (pre-existing; verified + one row added) |

Tier gating stays server-side (`tiers.py: visible_sections()`); the admin tables must never appear
in logged-out HTML. The public section's "something broken mid-match" footer deliberately names **no
admin command** — it says "ping an admin", nothing more.

## 5. Deliberately omitted from the page — and why

Recorded so the next editor doesn't re-add all 54. "Full inventory minus these" = what renders.

| Omitted | Why |
|---|---|
| `.cmds` / `.commands` | The page *is* the command list. In-game discovery still works. |
| `.score` | **Dropped by operator (2026-08-05): "rarely used by anyone."** Was on the page (Ready & score group + match-flow strip); removed in the visual refinement pass. `.status` already reports the score while live, so nothing is lost. Do not re-add. |
| `.prestatus`, `.whoneedsready` | Subsumed by `.status`; three status commands on a quick reference is two too many. |
| `.nodc` / `.stopdc` | Cancels the disconnect auto-pause countdown (affected team only). Rare, self-explanatory in the moment (the server prints the countdown and the command), and teaching it invites cancelling pauses that should happen. One fineprint line explains the auto-pause instead. |
| `.ext` / `.extend` | **Dead by default config**: `ktp_pause_max_extensions` defaults to `0` (:4016), so the command answers "Maximum extensions (0) already used." Listing it would document a feature that doesn't work. Re-add if the fleet ever enables extensions. |
| `.otbreak` | **The OT-break subsystem was never built** — the handler itself says so and prints "not currently supported" (:6068–6071). Documenting it would be documenting an apology. |
| `.skip` | Only meaningful inside the half-built OT-break flow above. |
| `.names`, `.resetnames`, `.setallies`, `.setaxis` | Custom team-name cosmetics for `.ktp`/`.draft` pre-start. Real but niche; the feature announces itself in chat during pre-start. |
| `.notconfirm` | Backing out of pre-start is what `.cancel` communicates; two near-synonyms on one line confuse more than they help. |
| `.cfg` | Diagnostic dump (ready counts, tech budgets, cfg lookup). Admin/debug audience; admins know it. |
| `.override_ready_limits` | Hardcoded-SteamID testing tool. Not even most admins can run it; on a reference it is pure noise. Not rendered in **any** tier. |
| `ktp_kick` / `ktp_ban` / `ktp_unban` / `ktp_changemap` console forms | Console duplicates of the chat commands; the chat forms are canonical. |
| `KTP_TEST_MODE` rcon commands (`cmd_test_*`) | Compile to zero bytes in production builds. |

## 6. Bot command hub (KTP tier) — verified against `KTPAdminBot/cogs/`

The pre-existing prototype tables were checked row-by-row against `ops_commands.py`,
`ac_commands.py`, `league_commands.py`. Result: **accurate**, one gap — `/ac session bundle`
(evidence-ZIP one-time link, `ac_commands.py:96`) was missing and is now added; it is core to the
review workflow. Everything else kept as-is: the hub serves ~a dozen admins, was already grouped
sanely, and heavier curation there buys nothing.

## 7. "What else belongs on this page" — decisions

All four operator-approved items landed, shaped by the density constraint ("if we can fit it and
not make the site look clunky"):

1. **Connect strings — accepted, on the status grid, not as a table.** A second 24-row list would
   duplicate the fleet grid and drift from it. Each existing instance row gains a small `connect`
   copy button (`connect <ip>:<port>`). **Contract change required:** `public.json` (§6 of
   DESIGN.md) gains one whitelisted field, `connect`, per instance. This is a deliberate,
   operator-approved amendment to the "no ports in the public file" rule — the endpoints are
   already public via the server browser; the allowlist principle (poller writes only named
   fields) is unchanged. DESIGN.md §6 should be updated when this goes real. Down instances
   render no button.
2. **Match-flow cheat sheet — accepted, as the 7-step visual strip** heading the commands section.
   Not prose; each step names its command. First-time captain reads it in five seconds.
3. **Tech-pause budget — accepted, as one callout,** not a section: the 300s-per-match rule, the
   4:00/1:00 example, OT's fresh budget, and the resume ceremony. Doubles as the ".pause is
   disabled" warning, which is the single most valuable sentence on the page.
4. **Cvar-kick + download troubleshooting + demos/spectating — accepted, as three collapsed items
   in the report sidebar** ("Before you report"), not a FAQ section. Placement is the point:
   answered at the moment of filing, each deflects a report. Demos/watch also remain hub cards —
   the sidebar line serves the "my match wasn't recorded?" reporter, the hub serves browsing.

Evaluated and **rejected**:

- **Which-server-to-book guidance on the public page** — rejected for public; shipped **admin-tier**.
  Core-sibling topology is scheduling guidance for people who book matches, meaningless to players,
  and would invite "why is my server the bad core" noise. Admin panel states the three facts
  (prefer #1; never #4+#5 of one city simultaneously; Chicago exempt) without CPU numerology.
- **A public "if something goes wrong" command group** — rejected. Every recovery command is
  ADMIN_RCON-gated, and the tier rule forbids admin commands in public markup. The public footer
  routes to Discord/report instead; wrongly telling a player they can run `.forcereset` is worse
  than omitting it.
- **AC client download link/section** — rejected as a section. `ac.ktpdod.com` owns install and
  policy; this page links to it from the hub and the cvar-kick item. Duplicating install docs
  here creates a second copy to rot.
- **Server rules / league schedule / standings** — out of scope; league content belongs to the
  Sheets-driven tooling and Sears' root site (DESIGN.md §G.2).

## 8. Known ambiguities (stated, not guessed)

- **`.confirm` "captain" semantics:** the first confirmer per team is recorded as that team's
  captain (`cmd_pre_confirm` :7342) — any team member can be it. The page says "one player from
  each team", which is what the code does.
- **Ready threshold:** default 6 per team, cvar-overridable per config; the page says
  "6 per team (default)".
- **Scrim/12man Discord routing** differs from official matches (`g_disableDiscord` set by their
  handlers); irrelevant to players, so unmentioned.
- **The season password itself** obviously never appears anywhere on this site, any tier.
