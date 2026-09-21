### `monitoring`: a fault's age stops being measured from the moment we happened to notice it (2026-09-21)

Every age this estate reported for a health item was measured from `since` in
`/var/lib/ktp-data-server-health.json` — the first run of the hourly check that *saw* the item. That is
a detection date, not an onset, and the two are only equal when the fault started after the watcher did.

Measured read-only on `neindataatl`: `ktp-identity-reconcile.service` entered `failed` on **2026-09-08
09:01:53** (recovered from `syslog.4.gz`, with a nonsense-token control on the same `zgrep` to prove the
instrument) and has never been active since — `systemctl --failed` still lists it, `NRestarts=0`, and the
only two runs in the surviving archives, 09-08 and 09-15, both exit 1. `systemctl --failed` became a
producer for the health check on 2026-09-16, so the item was stamped **2026-09-17 01:17:03**. At the
15:17 check the true age was **13.3 days** and the fleet audit's gate read **4.6** — a 65% under-count,
and under-counting is the direction that keeps a fault below a threshold rather than above it. A fault
older than its own watcher can sit under the 3-day gate indefinitely, and the gate is the thing that
decides whether a human is told at all.

`ktp-data-server-health.sh` now writes **`fault_since`** beside `since`: an onset taken from systemd's
`InactiveEnterTimestamp`, sparse like `detail` — present only where something durable knows, absent
rather than null where nothing does. It is clamped to `since` and to its own carried value, so it only
ever moves *earlier* while an item stays down. That last part is what makes the state file useful rather
than decorative: a periodic unit that fails, stays failed and fails again resets systemd's stamp, and
journald here holds about two days against a weekly unit while syslog rotates in about one — so this file
is the only artefact on the box that can carry an onset at all.

`fleet-audit-gate.sh` and support-web's incidents list both age off `fault_since` when present and fall
back to `since` otherwise, so an absent field cannot silence either. The incidents list also *sorted* on
the detection date, which pushed a late-noticed fault below a newer one; it now sorts on the onset and
shows "first seen" beside the date only where the two disagree. The weekly triage prompt named `since`
as "since when" and is corrected.

The probe refuses more than it answers, deliberately. `date -d ""` prints today at midnight and exits 0,
so an unset property would have landed as a *fresh* timestamp — the one direction that hides a fault —
and the raw string is shape-checked before `date` sees it. `LoadState` is asked for because a unit that
does not exist answers `inactive`/`dead`, byte-identical to a real stopped one; `ActiveState` is asked
for because `InactiveEnterTimestamp` on a *running* unit is its last clean stop, which on `mysql.service`
would have dated a fault from a healthy restart nine days earlier. All three refusals are tested, and
verified against the live box.

Nothing about severity or routing changes, and no item appears or disappears: `ktp-identity-reconcile`
exits 1 **to raise findings**, not because it crashed, and this only changes the number beside it.
Because the onset is clamped to `since`, an item can only ever read older than it does today — the gate
can fire more, never less.

**Deploy:** the gate and the workflow ride the checkout, so Monday's audit picks them up. The producer
does not — `/usr/local/bin/ktp-data-server-health.sh` is a deployed copy and is already behind `main`.
Until it is redeployed the new field is simply absent and both consumers fall back to `since`, which is
today's behaviour.

**Still uncovered, stated rather than hidden:** the 09-08 date above exists only in `syslog.4.gz` and in
`ALERT_COVERAGE.md` prose; nothing the check can read knows it, so the live item will back-date to
09-15 and no further. Only `failed-unit:` items have a durable onset signal — `disk-growth:`, the HLTV
coverage legs and the capture checks have none, and none is invented for them.
