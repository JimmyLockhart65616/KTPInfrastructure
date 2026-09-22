### `analytics`: round resets were priced as swings; cap-outs and fast pushes now have names (2026-09-22)

Reported by a player against `1789931256-NY1` (RenameD vs. over, 2026-09-20):
a cap-out taken behind enemy lines and a mid cap taken as the enemy took his
team's home flag, neither of which appeared anywhere in the analysis.

Chasing them found a pricing defect. When a side caps out, the engine
neutralises every flag at one timestamp. `flag_swing` priced those rows as
ownership changes, so the winning team was booked **losing** everything it had
just won: on that match a cap-out worth −0.112 followed three seconds later by
+0.381 of phantom swing credited to nobody, P(win) walked back to 0.500.
Across the corpus 596 resets (62 in officials) made roughly 8% of all timeline
movement artifact, and it reached `key_moments` — one window there was half
reset noise.

- A mass neutralisation is now a **boundary**: no deltas, one `round` row
  naming the winner and whether it was a cap-out or the clock, and the state
  machine starts the next round from the cleared map. `highlight_windows`
  skips those rows so a reset can never rank as a moment.
- The cap that ends a round carries `capout_completed`; `plays` tags it
  `cap-out`.
- `excursions` gains `touches`: every rear-flag capture measured on its own
  terms — the gap to the capper's nearest living teammate at the moment of the
  touch, his depth, and how much depth he gained in the ten seconds before.
  That is the **fast push** (tagged as such): a player who goes in with the
  team, breaks off for the last seconds and takes the flag ahead of everyone.
  The reported cap-out is one — teammates 95–358 units away through the push,
  824 → 1362 at the touch, enemies closer than his own side. The ten-second
  isolation window the ninja rule needs never formed, which is why nothing
  saw it.
- `capture_credit_timeline_fact.sql` now derives `game_time` from the matching
  flag transition; `ktp_flag_captures` has no game clock of its own.

**Not fixed here, on purpose:** a round win is labelled, not priced. The
closing cap still prices as an ordinary flag flip, so a cap-out can rank below
a mid cap — the reported one values at +0.112 against mid caps at +0.19. What a
round win is worth belongs to the momentum ledger's fit, not to a number chosen
by hand. Both envelopes say so.
