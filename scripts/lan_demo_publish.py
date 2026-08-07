#!/usr/bin/env python3
"""Publish the Philly LAN demos under the production canonical name + demos/ layout.

Production convention (hltv-demo-renamer.py + ktp-organize-hltv-demos.sh):
    <matchtype>_<match_id>-<UPPER_FRIENDLY>(_h1|_h2)?-<hltv_ts>-<map>.dem
    sorted into  demos/<HOSTNAME>/<matchtype>/
LAN keeps that shape so the archive reads the same as every other demo, with the
friendly name carrying LAN<n> and the whole event under one LAN- prefixed folder.

HARDLINKS, not copies: the archive is now the ONLY copy of these 1,863 files, and
/opt and /home are the same filesystem, so linking costs no space and cannot lose
the original. A move would put the sole copy behind a web root.

Run with --apply to make changes; default is a dry run.
"""
import argparse, csv, json, os, re, collections

AR = "/opt/ktp-lan-archive/philly-2026"
SRC = AR + "/demos"
DEST_ROOT = "/home/hltvserver/hlds/dod/demos/LAN-PHILLY2026"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

windows = {m["id"]: m for m in json.load(open(AR + "/match_windows.json"))}
parsed = {d["name"]: d for d in json.load(open(AR + "/demos_parsed.json"))}

rows = list(csv.DictReader(open(AR + "/match_index.csv")))
print("matches in index: %d" % len(rows))

planned = []          # (src, dest, matchid)
skipped = []
for r in rows:
    mid = r["match_id"]
    mtype = r["type"] or "unknown"
    lan = r["lan"]                                   # e.g. "lan1"
    friendly = "LAN" + re.sub(r"\D", "", lan)        # -> LAN1
    demos = [x for x in (r["demo_files"] or "").split(";") if x.strip()]
    win = windows.get(mid, {})
    halves = win.get("halves", {}) or {}
    h2_start = halves.get("h2")

    # order by actual recording start, not filename order
    demos.sort(key=lambda n: parsed.get(n, {}).get("start", 0))
    per_half = collections.Counter()
    for name in demos:
        info = parsed.get(name)
        if not info:
            skipped.append((name, mid, "not in demos_parsed")); continue
        if not os.path.exists(os.path.join(SRC, name)):
            skipped.append((name, mid, "missing on disk")); continue

        # A match's demos split across halves; assign by which half the recording
        # starts in. Halves are ~20 min and HLTV rotates on the same cadence, so a
        # half can own more than one file -> _partN, exactly as production does.
        half = "h1"
        if h2_start and info["start"] >= h2_start - 60:
            half = "h2"
        per_half[half] += 1
        part = "" if per_half[half] == 1 else "_part%d" % per_half[half]

        m = re.match(r"auto_lan\d+-(\d{10})-(.+)\.dem$", name)
        if not m:
            skipped.append((name, mid, "unparsable name")); continue
        ts, mapname = m.group(1), m.group(2)

        newname = "%s_%s-%s_%s-%s-%s%s.dem" % (mtype, mid, friendly, half, ts, mapname, part)
        planned.append((os.path.join(SRC, name),
                        os.path.join(DEST_ROOT, mtype, newname), mid))

print("planned links : %d" % len(planned))
print("skipped       : %d" % len(skipped))
for s in skipped[:8]:
    print("   %s (%s) — %s" % s)

by_type = collections.Counter(p[1].split("/")[-2] for p in planned)
print("by match type : %s" % dict(by_type))
# collisions would silently overwrite -- catch before writing anything
dests = [p[1] for p in planned]
dupes = [d for d, c in collections.Counter(dests).items() if c > 1]
print("name collisions: %d" % len(dupes))
for d in dupes[:5]:
    print("   ", d)

print("\nsample names:")
for _, dest, _ in planned[:6]:
    print("   %s" % dest.replace(DEST_ROOT + "/", ""))

if not args.apply:
    print("\nDRY RUN — nothing written. Re-run with --apply.")
    raise SystemExit(0)

if dupes:
    print("\nABORT: collisions would overwrite. Nothing written.")
    raise SystemExit(1)

made = relinked = 0
for src, dest, _ in planned:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        if os.path.samefile(src, dest):
            relinked += 1; continue
        os.remove(dest)
    os.link(src, dest)
    made += 1
print("\nlinked: %d new, %d already correct" % (made, relinked))

total = sum(os.path.getsize(p[1]) for p in planned)
print("published: %d files, %.1f GB (hardlinked — no extra disk used)" % (len(planned), total / 1e9))
