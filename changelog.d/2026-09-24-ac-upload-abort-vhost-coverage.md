### `monitoring`: the aborted-upload detector now asserts it still has an input (2026-09-24)

`ac-upload-abort` reads one access log, because exactly one nginx server block writes a
format carrying `$upstream_response_time`. That is an accident of the upload vhost needing
`rt`/`urt`/`rl` for its own reasons, not a decision anyone made about alerting. Measured on
the data server the same day: **22 server blocks, 1 covered, 21 not**, and the one covered
block is the `:443` half of the upload vhost — its own `:80` twin inherits the shared
`access.log` and `combined`, so coverage is per block, not per `server_name`.

- **`ktp-data-server-health.sh` gains `ac_upload_urt_coverage`.** Once per run it reads
  `nginx -T` — the effective config, so a vhost that is enabled by symlink and invisible to a
  `grep -r` of `sites-enabled` is still counted — and resolves each server block to the log it
  writes and that log's format. Each block is walked with a brace counter that starts fresh at
  the block, so a miscount elsewhere in the dump cannot quietly shift another vhost's verdict.
- **The accepted gap is printed, never alerted.** Every other vhost logs `combined` and runs at
  the default `error` level, so an aborted transfer there is absent from the error log *and*
  unclassifiable in the access log at the same time. An item that can only clear by someone
  editing nginx would latch down forever and train the reader to ignore the key, so the
  covered/uncovered split goes in the hourly report line with the uncovered blocks named. It
  shrinks visibly when someone closes it.
- **The regression does alert, against a baseline rather than an absence.**
  `ac-upload-abort=coverage-regressed` fires when a log in `AC_UPLOAD_URT_LOGS` no longer
  resolves to a urt-capable format, or when no server block writes it at all. That is the
  failure the existing legs cannot reach: if the upload vhost's format is edited back to
  `combined`, the scanner returns a clean 0 out of real traffic, and `=unmeasurable` only
  notices while the window holds upload lines — on a quiet night `scanned` is 0 and the field
  could have been gone for days.
- **`=coverage-unmeasurable` keeps an unreadable config from reading as covered**, the same
  shape as `=log-unreadable`.
- **Duplicate labels carry a multiplier.** Two blocks share one label whenever a vhost has a
  `:443` and a `:80` half; on the live config seventeen labels stand for twenty-one blocks, and
  a name list shorter than the count beside it reads as a parser that lost something.
- `tests/unit/test_health_ac_upload_coverage.py` extracts the function by marker — renaming or
  deleting it fails the file rather than testing a copy that no longer ships. It carries both
  controls: a format name that does not exist must never read as urt-capable, and nginx's
  built-in `combined`, which is declared in no config file, must still resolve.

Validated against the live effective config: the shipped function independently reproduced
22/1/21 with `lost` empty, and a baseline pointed at a log nothing writes reported it.
