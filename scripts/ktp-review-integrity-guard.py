#!/usr/bin/env python3
"""Run the AntiCheat review-integrity guard on a schedule and alert only on a NEW finding.

WHY A WRAPPER. `check-clean-over-flagged.py` (canonical: KTPAntiCheat/scripts/) is built to
be run by hand from a workstation: it opens SSH to the data server and pulls its own
snapshot. On the data server that transport is a loopback with no purpose, and the box's
root key is deliberately not in its own authorized_keys. So this asks the guard for its SQL,
runs it against the local socket, and hands the result straight back to the guard through
the same --snapshot path a hand run uses. The SQL, the controls, the window rule and the
exit contract all stay in the guard. Nothing here re-implements any of them.

WHY IT ALERTS. A cron that appends to a log nobody reads is not a guard. Findings go to
Discord through the existing relay, and only when the finding set GAINS a session -- a
standing finding re-posted every morning is the fastest way to teach everyone to mute the
channel, and a muted guard is the defect it was built to catch.

EXIT 2 ALWAYS POSTS. "Could not look" reading as "nothing there" is the exact shape of the
failure the guard exists for, so a broken pull is louder than a finding, not quieter.

A DERIVATION FAILURE POSTS TOO. The new-session test parses the same pull the guard read;
if it comes back empty while the guard reports findings, this posts rather than suppresses.
The dedup may only ever cost a duplicate message, never a missed one.

Exit code is the guard's own, unchanged: 0 clean, 1 findings, 2 cannot check.

Usage:
    ktp-review-integrity-guard --since YYYY-MM-DD
    ktp-review-integrity-guard --since YYYY-MM-DD --dry-run     # print the embed, post nothing
    ktp-review-integrity-guard --since YYYY-MM-DD --always-post # ignore the new-session test

Config: /etc/ktp/discord-relay.conf supplies RELAY_URL and AUTH_SECRET. REVIEW_GUARD_CHANNEL
there overrides the destination channel.
"""
import argparse
import contextlib
import datetime
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.request

GUARD_PATH = os.environ.get("KTP_REVIEW_GUARD_SCRIPT",
                            "/usr/local/bin/ktp-check-clean-over-flagged.py")
RELAY_CONF = os.environ.get("KTP_RELAY_CONF", "/etc/ktp/discord-relay.conf")
STATE_DIR = os.environ.get("KTP_REVIEW_GUARD_STATE_DIR", "/var/lib/ktp-review-integrity-guard")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
PULL_FILE = os.path.join(STATE_DIR, "last-pull.tsv")
DB = os.environ.get("KTP_AC_DB", "hlstatsx")
# Scheduled-report channel, the same destination ktp-soak-verify posts its findings to.
DEFAULT_CHANNEL = "1498813261263405097"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def load_conf(path):
    """Strips quotes off values -- an unquoted read turns RELAY_URL into a literal scheme."""
    conf = {}
    if not os.path.exists(path):
        return conf
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
    return conf


def load_guard(path):
    spec = importlib.util.spec_from_file_location("ktp_clean_over_flagged", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("guard script is not importable: " + path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pull(guard, severity_source):
    sql = guard.snapshot_sql(severity_source)
    p = subprocess.run(["mysql", "-N", "-B", "--raw", DB], input=sql,
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("mysql exited %d: %s" % (p.returncode, p.stderr.strip()[:300]))
    return p.stdout


def derive_hits(guard, text, since):
    """Best effort, for the alert test only -- never for the verdict. None means unknown."""
    try:
        hits = guard.Snapshot.parse(text).hits
    except Exception:
        return None
    if since:
        hits = [h for h in hits
                if not (h["reviewed_at"] not in ("-", "") and h["reviewed_at"] < since)]
    return [h["id"] for h in hits]


def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(state):
    os.makedirs(STATE_DIR, mode=0o750, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_FILE)


def build_embed(rc, ids, new_ids, report, since):
    """No steam_id, no bundle name, no reviewer -- session ids and counts only. The
    reviewing actor is in the log on the box, which is where acting on this starts."""
    if rc == 2:
        first = next((l for l in report.splitlines() if l.startswith("CANNOT CHECK")), "")
        return {
            "title": "AC review-integrity guard: CANNOT CHECK",
            "description": ("The guard could not trust its pull, so it reported no verdict. "
                            "A check that cannot look is not a clean corpus.\n\n" + first)[:1900],
            "color": 0xE67E22,
            "footer": {"text": "ktp-review-integrity-guard, data server"},
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    shown = ", ".join(new_ids[:15]) + (" ..." if len(new_ids) > 15 else "")
    return {
        "title": "AC review integrity: undocumented clean-over-flagged",
        "description": ("A session was stamped clean over a flagged verdict with no rationale "
                        "recorded, so the override cannot be defended or reviewed."),
        "color": 0xC0392B,
        "fields": [
            {"name": "new since last alert", "value": str(len(new_ids)), "inline": True},
            {"name": "open in window", "value": str(len(ids)), "inline": True},
            {"name": "window",
             "value": ("reviewed on or after " + since) if since else "all time",
             "inline": True},
            {"name": "sessions", "value": shown or "(see the log)", "inline": False},
            {"name": "fix", "value": "Record the rationale on the session, or correct the "
                                     "disposition. Do not widen the predicate.", "inline": False},
        ],
        "footer": {"text": "detail: /var/log/ktp-review-integrity-guard.log"},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def post(embed, channel, conf):
    url, secret = conf.get("RELAY_URL", ""), conf.get("AUTH_SECRET", "")
    if not url or not secret:
        return False, RELAY_CONF + " is missing RELAY_URL or AUTH_SECRET"
    req = urllib.request.Request(
        url, data=json.dumps({"channelId": channel, "embeds": [embed]}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-Relay-Auth": secret})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return (200 <= r.status < 300), r.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="passed straight to the guard; it prints what it excluded")
    ap.add_argument("--severity-source", default="either",
                    choices=("client", "server", "either"))
    ap.add_argument("--channel", default=None, help="Discord channel id")
    ap.add_argument("--dry-run", action="store_true", help="print the embed, post nothing")
    ap.add_argument("--always-post", action="store_true", help="skip the new-session test")
    args = ap.parse_args(argv)

    conf = load_conf(RELAY_CONF)
    channel = args.channel or conf.get("REVIEW_GUARD_CHANNEL") or DEFAULT_CHANNEL
    # astimezone() first: a naive now() renders %Z%z empty, and a log line whose zone is
    # implicit is a log line somebody will read in the wrong one.
    print("===== ktp-review-integrity-guard " +
          datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z (%z)"))

    buf, text, guard = io.StringIO(), "", None
    try:
        guard = load_guard(GUARD_PATH)
        text = pull(guard, args.severity_source)
        os.makedirs(STATE_DIR, mode=0o750, exist_ok=True)
        fd = os.open(PULL_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        gargs = ["--snapshot", PULL_FILE, "--severity-source", args.severity_source]
        if args.since:
            gargs += ["--since", args.since]
        with contextlib.redirect_stdout(buf):
            rc = guard.main(gargs)
    except Exception as e:
        rc = 2
        buf.write("CANNOT CHECK: %s: %s\n" % (type(e).__name__, e))

    report = buf.getvalue()
    sys.stdout.write(report if report.endswith("\n") else report + "\n")

    state = read_state()
    known = state.get("alerted_ids") if isinstance(state.get("alerted_ids"), list) else []
    ids = derive_hits(guard, text, args.since) if (guard is not None and text) else None
    new_ids = [i for i in ids if i not in known] if ids else []

    if rc == 0:
        should, reason = False, "clean run -- silent by design"
        state["alerted_ids"] = []
    elif rc == 2:
        should, reason = True, "cannot check"
    elif args.always_post:
        should, reason = True, "--always-post"
        new_ids = ids or []
    elif not ids:
        should = True
        reason = ("findings reported but the session list could not be derived -- "
                  "posting rather than suppressing")
        new_ids = ["(underivable)"]
    elif new_ids:
        should, reason = True, "%d session(s) not in the last alert" % len(new_ids)
    else:
        should, reason = False, "same session set as the last alert -- already surfaced"

    print("exit=%d  alert=%s  (%s)" % (rc, "yes" if should else "no", reason))

    if should:
        embed = build_embed(rc, ids or [], new_ids, report, args.since)
        if args.dry_run:
            print("DRY RUN, not posted:\n" + json.dumps(embed, indent=2))
        else:
            ok, resp = post(embed, channel, conf)
            print("discord post: %s %s" % ("ok" if ok else "FAILED", resp))
            if ok and rc == 1 and ids:
                state["alerted_ids"] = ids

    state["last_run"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["last_rc"] = rc
    try:
        write_state(state)
    except Exception as e:
        print("warning: could not write %s: %s: %s" % (STATE_FILE, type(e).__name__, e))
    return rc


if __name__ == "__main__":
    sys.exit(main())
