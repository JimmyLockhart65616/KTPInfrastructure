# Estate cron inventory

A captured snapshot of **every** scheduled job across the KTP estate — 7 hosts, taken
2026-08-06. This exists because scheduled work kept living only on the boxes: a job would be
written, do its work for months, and be invisible to anyone reading this repo. When something
was lost or changed, there was nothing to diff against.

```
ops/cron-inventory/<host>/crontab-<user>.cron    user crontabs
ops/cron-inventory/<host>/cron.d/<name>          /etc/cron.d entries
```

Hosts: `data`, `atlanta`, `dallas`, `denver`, `newyork`, `chicago`, `lanbox`.

## This is a SNAPSHOT, not the source of truth

Nothing reads these files. The live crontabs are still authoritative, so a job changed on a box
does not change here. **Re-capture after any cron change** and commit the diff — that diff is the
whole point.

## Secret scan

Every file was scanned before committing: the known credential set (fleet SSH, data-server root,
LAN box, game rcon, MySQL, FTP, HLTV admin/API) plus generic `password|secret|token|api_key=` and
Discord webhook patterns. **0 findings across 39 files** — cron here invokes scripts, and those
scripts source their secrets from `/etc/ktp/*.conf`, which is the reason this is publishable at all.

⚠️ **Re-run the scan before committing a refresh.** This repo is PUBLIC, and it is how the fleet
SSH password leaked in 2026-05. A scan that reports zero is only meaningful if it can report
non-zero: control-test it against a known-bad string first.

## Scripts referenced by these jobs

16 distinct scripts. All are now in `scripts/` or `monitoring/` — `ktp-demo-retention.sh` and
`ktp-fleet-audit.sh` were the two that existed only on the data server until this commit.
