### `flag_swing`: one test for "owns every flag", not two (2026-09-22)

#497's `capout_completed` and #500's top-level `capouts` landed within a day of
each other and each wrote out the same condition — `not is_initial_row and
owner in (1,2) and flags_held(owner) == flag_count` — eight lines apart in the
event loop. They agreed, but the next edit to either would have drifted them
silently. Hoisted to one `owns_every_flag` local that both read, with a test
pinning them together: a no-op re-transition during one hold is invisible to
both, and a fresh round in the same half rearms both. No behaviour change.
