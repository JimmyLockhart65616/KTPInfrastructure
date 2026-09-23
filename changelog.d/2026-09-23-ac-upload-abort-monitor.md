### `monitoring`: an AC evidence bundle that never arrives is now a state (2026-09-23)

Six session bundles were lost in the fortnight to 2026-09-22 and nothing anywhere said a word.
Every one was an aborted transfer: the client stopped sending mid-body, nginx answered it
directly, and `urt=-` records that `ktp-ac-api` was never contacted — so no AC-side log, table
or counter holds a trace, and the bundle does not exist. The sharpest cluster was three aborts
and a 408 inside nine minutes of a match-end herd, while neighbouring uploads in the same second
completed. nginx *does* log the cause — "client prematurely closed connection" — at `info`,
below the default `error` level, which is why `api.ktpdod.com.error.log` has been 0 bytes since
2026-07-18. The class was invisible by configuration, not by absence.

- **`ktp-data-server-health.sh` gains `ac-upload-abort`.** Once per run it reads today's and
  yesterday's `api.ktpdod.com.access.log` over a trailing 6h and counts requests on
  `/api/session/upload` that nginx answered itself — `urt=-` — with a 4xx or 5xx. Warn 1: one
  aborted upload is one permanently lost bundle. `AC_UPLOAD_ABORT_CLEAR` must stay at or above
  1; at 0 the mid-band test in `latched` holds for every count and the item never clears again.
- **The discriminator is `urt`, never the status.** On 2026-09-20 at 21:03:40 the API itself
  answered 400 in 16 ms to a 34 KB body — a bundle that arrived and was rejected, which is a
  different problem and already visible AC-side. Internet scanners produce `400 urt=-` on `/`
  all day. Both are excluded by construction. Over the retained fortnight the rule matches five
  lines and every one is a real loss.
- **`ac-upload-abort=unmeasurable` is the leg that survives rotation.** `rt`/`urt`/`rl` only
  exist from the 2026-09-16 `log_format` change; lines written before it structurally cannot
  carry `urt`, so scanning one of those files returns zero aborts out of real traffic —
  `api.ktpdod.com.access.log.10.gz` holds 21,766 lines and 127 real session uploads and scores
  0. In-window lines with no `urt=` are counted, never dropped, and reported beside the abort
  count so it reads as a lower bound rather than a clean bill of health. A line whose timestamp
  will not parse is counted the same way: it cannot be placed inside or outside the window, so
  it cannot be dismissed. `=window-unsupported` refuses a window over 24h rather than reading
  short, since only today's and yesterday's logs are plain text under `delaycompress`, and
  `=log-unreadable` keeps a missing log from reading as perfect health.
- **A burst is one alert.** The key carries no number — the count rides in `detail` — so the
  hourly set comparison sees one item appear and one item clear. Replayed against the real
  2026-09-20 log at each `:17` cron run the count goes 0, 4, 4, 4, 4, 4, 4, 1, 1, 0: the
  transition report speaks when it starts and when it ends, and says nothing in between. The
  trade is explicit — a second, worse burst while the item is already down is silent until it
  clears, and the running count is in `/var/log/ktp-data-server-health.log` every hour.
- `tests/unit/test_health_ac_upload_abort.py` extracts the scanner and the latch by marker.
