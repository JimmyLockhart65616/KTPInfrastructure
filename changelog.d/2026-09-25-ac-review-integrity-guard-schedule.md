### `monitoring`: schedule the AntiCheat review-integrity guard on the data server (2026-09-25)

`check-clean-over-flagged.py` (KTPAntiCheat, merged in that repo's #362) finds sessions
stamped `clean` over a `flagged` verdict with no rationale recorded — an override nobody can
defend and nobody can review. It shipped as a hand-run script with a test suite and a CI job,
which means it only ever answers when somebody remembers to ask it. This puts it on a daily
schedule on the data server and gives it somewhere to shout.

- `scripts/cron.d/ktp-review-integrity-guard` — 06:15 ET daily, clear of the 03:00 fleet
  restart, the 03:30 soak verify, the 04:30 perf rollup, the 04:40 AC retention sweep and the
  05:00 digests, and early enough that a finding is read with the morning's Discord.
- `scripts/ktp-review-integrity-guard.py` — the wrapper the cron line runs. The guard is
  written to SSH into the data server and pull its own snapshot; on the data server that is a
  loopback to nowhere, since root's key is deliberately not in root's `authorized_keys`. The
  wrapper asks the guard for its SQL, runs it on the local socket, and hands the result back
  through the guard's own `--snapshot` path. Every SELECT, control and exit code stays in the
  guard; nothing here re-implements any of them, and the wrapper's exit status is the guard's.
- `scripts/ktp-review-integrity-guard.logrotate` — monthly, twelve kept. The log is the only
  place the reviewing actor behind a finding is written down, because the Discord embed carries
  session ids and counts and nothing else on purpose.

Alerting rules, in the order they were argued:

- A clean run posts nothing. A guard that speaks every morning is a guard everyone mutes.
- A finding posts only when the finding set GAINS a session, tracked in
  `/var/lib/ktp-review-integrity-guard/state.json`. A standing finding re-announced daily is
  the same mute problem wearing a red embed.
- **Exit 2 always posts.** "Could not look" reading as "nothing there" is the exact shape of
  the defect the guard was built for, so a broken pull is louder than a finding, not quieter.
- If the guard reports findings and the wrapper cannot derive the session list from the same
  pull, it posts anyway. The de-duplication may cost a duplicate message; it may never cost a
  missed one.

⚠️ The `--since` watermark in the cron line is not a filter that hides anything. The findings
that predate it are a historical set that stopped in July, and the operator's decision is not
to hand-triage them; the guard prints how many it excluded and says they are still open, on
every run including a clean one. Moving that date forward to silence a finding is the one
change to this job that nobody should make quietly.

Deploy is a file copy plus `/etc/cron.d` and `/etc/logrotate.d` drops — cron re-reads
`/etc/cron.d` on its own, so nothing needs reloading or restarting.
