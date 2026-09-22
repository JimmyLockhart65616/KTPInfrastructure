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

- A round-ending cap now carries `terminal_value`: the probability still
  outstanding when it was taken, `1 - P(the capping side wins the round)`.
  A closing play realises the outcome rather than shifting it, so it is worth
  what was left — derived from the model, not a chosen constant. Closing a
  round already 95% won is worth 0.05; closing a coin-flip is worth 0.50.
  Across S10 officials that moves cap-outs from a median 0.112 (an ordinary
  flag flip) to 0.231. `delta` is unchanged, so a consumer reading only
  `delta` sees exactly what it saw before. `plays` values a `cap-out` on it,
  split across the credited cappers — three players on the flag share what one
  player closing it alone keeps. The reported cap-out goes from sixth in its
  player's list to first.

**Not done here:** the round win is not yet redistributed to the teammates who
set it up — a player who cleared the way and died seconds before the touch
gets nothing from it. That split is the momentum ledger's fitted job
(`scripts/mmr/momentum.py`, measured cap-out lift 4.7x at 0-15 s, so roughly
four fifths of a cap-out's value should flow back to whoever produced it);
`terminal_value` is the per-event value that ledger has been missing.
