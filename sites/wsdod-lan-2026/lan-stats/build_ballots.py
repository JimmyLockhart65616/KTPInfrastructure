"""Build the award ballots into awards.json.

Every eligibility rule here is derived from the published stats, so re-running
this after the stats are reconfigured re-derives the lists. Every list is
derived; nothing here is typed in by hand.

Each ballot carries its criteria as data alongside the eligible list, because an
eligibility list with no stated rule is an assertion rather than a shortlist --
staff need to read the rule that produced a name in order to change it.

  rookies   neither name nor SteamID on a 2025 roster
  carry     played 2026, weekend K/D at or above the floor
  losing    same, minus the company that won it
  improved  played both LANs, 2026 weekend K/D above their 2025 K/D

Sorting is team then name everywhere, so a voter scanning for their own company
finds it in one place.

Re-runnable: it reads only the stats files and rewrites the ballots wholesale.
"""
import json
import os
import re
import unicodedata
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))

MIN_KD = 1.0
MIN_HALVES = 0          # no floor today; stated so it can be raised
MIN_GAIN = 0.0          # ditto -- 0.01 of K/D is an improvement until it isn't
LOSING_EXCLUDE = "North Atlantic Treaty Org"

# 2025 roster name -> the name that player's row carries on the 2025 stats
# board. Jane compiled that board from screenshots, so a handful of rows use a
# name the roster doesn't. Only pairs with corroborating evidence belong here:
# same team, and a contraction of the same name. LaNGoN and omenayr are the
# open cases -- Thunder has two unmatched roster names and two unmatched board
# rows, and nothing distinguishes which is which, so they stay unresolved.
CROSS_YEAR = {"pb": "paintball", "rolyat": "taylor", "ihc": "chi"}


def load(name):
    return json.load(open(os.path.join(BASE, name), encoding="utf-8"))


stats = load("lan-stats.json")
teams = load("player_teams.json")
aliases = load("player_aliases.json")
p25 = load("philly-2025.json")
s25 = load("lan-stats-2025.json")
awards = load("awards.json")

# ---- names, the same derivation the awards board uses ----------------------
by_team = defaultdict(set)
for day in stats["days"].values():
    for p in day["players"]:
        t = (teams.get(p["steam_id"]) or {}).get("team")
        if t:
            by_team[t].add(p["name"])
prefixes = []
for names in by_team.values():
    names = sorted(names)
    if len(names) < 2:
        continue
    pre = names[0]
    for n in names:
        i = 0
        while i < len(pre) and i < len(n) and pre[i] == n[i]:
            i += 1
        pre = pre[:i]
    if len(pre) >= 2:
        prefixes.append(pre)
prefixes.sort(key=len, reverse=True)


def short(n):
    """Drop the clan tag, which is a prefix shared across a team's names."""
    for p in prefixes:
        if n.startswith(p):
            s = n[len(p):].strip()
            if s:
                return s
    return n


def trim_flair(n):
    """Cut the shoutout people hang off the back of a name.

    The clan tag is a prefix and short() takes it; this takes the tail. "<3vt"
    and "4 jGaleZ" are the same gesture as "<3 dustbin" with the space closed
    up, so the marker is matched wherever it lands rather than only after a
    space. Verified against every alias in the corpus: it moves two names and
    touches no other — "Gorilla[bc]" and "warchyld[dd]" are handles, not flair.
    """
    for pat in ("<3", r"\s+4\s*\S", "＃", r"\s#", "#"):
        m = re.search(pat, n)
        if m and m.start() > 0:
            n = n[:m.start()]
    return n.strip(" -_") or n


def untag(name, known):
    """Drop a one-off tag the team-wide derivation can't see.

    short() strips the TEAM tag, found from what a team's names have in common.
    A tag worn for a single scrim is shared with nobody, so nothing strips it —
    "[team9] mogers" and "DAYMAN cory?" both reached the board with one on the
    front. The account's own other names are the evidence: if one of them is
    what this name ends with, the front of this name was a tag.

    Strictly a prefix cut. The account wore both "player" and "milo", and
    neither is a suffix of the other, so nothing here can decide it is really
    called milo — that is a different question and not one a rule should guess.
    """
    best = name
    for other in known:
        o = trim_flair(short(other))
        if len(o) >= len(best) or not best.lower().endswith(o.lower()):
            continue
        if best[len(best) - len(o) - 1].isalnum():   # a word must end, not split
            continue
        best = o
    return best


def canon(steam, seen_as=None):
    known = aliases.get(steam) or []
    seen = trim_flair(short(known[0] if known else (seen_as or steam)))
    return untag(seen, known)


def key(n, strip_tag=True):
    """Strip decoration so 'ßℓυ†н | kroD-' and '2025 kroD' can meet."""
    n = unicodedata.normalize("NFKD", short(n) if strip_tag else n).lower()
    n = re.split(r"[<＃#|]", n)[0]
    return re.sub(r"[^a-z0-9]", "", n)


# ---- 2026 weekend totals ---------------------------------------------------
agg = {}
for day in stats["days"].values():
    for p in day["players"]:
        q = agg.setdefault(p["steam_id"], {"name": p["name"], "kills": 0,
                                           "deaths": 0, "halves": 0, "seen": set()})
        q["name"] = p["name"]
        q["seen"].add(p["name"])
        for k in ("kills", "deaths", "halves"):
            q[k] += p.get(k) or 0
for steam, q in agg.items():
    q["kd"] = round(q["kills"] / q["deaths"], 3) if q["deaths"] else 0.0
    q["team"] = (teams.get(steam) or {}).get("team")
    q["who"] = canon(steam, q["name"])
    # 62 of 64 accounts played under more than one name over the weekend, so
    # asking whether "this player" was at 2025 means asking about every name
    # they used -- TillJim spent a day as SilverPlayer, and one name misses.
    q["keys"] = {key(n) for n in q["seen"] | set(aliases.get(steam) or [])}
    q["keys"].add(key(q["who"]))

# ---- 2025: rosters carry the SteamIDs, the stats board carries the K/D -----
# Matching 2026 -> 2025 on name alone loses 18 of 42 returning players, because
# tags and flair move between LANs. Going through the roster recovers them: the
# roster has ids, so a returning player is found by id and only then looked up
# on the board by the name the roster gives.
roster_by_id, roster_by_name = {}, {}
for t in p25["teams"]:
    for p in t["players"]:
        if p.get("steam_id"):
            roster_by_id[p["steam_id"]] = p["name"]
        roster_by_name[key(p["name"], False)] = p["name"]

kd25 = defaultdict(lambda: {"kills": 0, "deaths": 0})
for board in s25["boards"]:
    for r in board["players"]:
        e = kd25[key(r["name"], False)]
        e["kills"] += r.get("kills") or 0
        e["deaths"] += r.get("deaths") or 0
for e in kd25.values():
    e["kd"] = round(e["kills"] / e["deaths"], 3) if e["deaths"] else 0.0


def roster_2025(steam, keys):
    """Their 2025 roster name, or None -- the thing that makes them returning."""
    if steam in roster_by_id:
        return roster_by_id[steam]
    for k in keys:
        if k in roster_by_name:
            return roster_by_name[k]
    return None


def prior_kd(roster):
    """That player's 2025 K/D, or None if the 2025 board has no row for them."""
    k = key(roster, False)
    e = kd25.get(CROSS_YEAR.get(k, k))
    return e if e and e["deaths"] else None


def rows(entries):
    """Team then name, the order a voter scans in."""
    return sorted(entries, key=lambda r: ((r["team"] or "~~").lower(),
                                          r["name"].lower()))


# ---- Best Rookie -----------------------------------------------------------
rookies = rows([{"name": q["who"], "team": q["team"], "note": None}
                for s, q in agg.items() if not roster_2025(s, q["keys"])])
returned = len(agg) - len(rookies)

# ---- Carry Us, Daddy / Best On A Losing Team -------------------------------
qualified = [{"name": q["who"], "team": q["team"], "note": "%.2f K/D" % q["kd"]}
             for q in agg.values()
             if q["kd"] >= MIN_KD and q["halves"] >= MIN_HALVES]
carry = rows(qualified)
losing = rows([r for r in qualified if r["team"] != LOSING_EXCLUDE])

# ---- Most Improved ---------------------------------------------------------
improved, both, unresolved = [], 0, []
for steam, q in agg.items():
    roster = roster_2025(steam, q["keys"])
    if not roster:
        continue
    both += 1
    prior = prior_kd(roster)
    if not prior:
        unresolved.append(q["who"])
    elif q["kd"] - prior["kd"] > MIN_GAIN:
        improved.append({"name": q["who"], "team": q["team"],
                         "note": "%.2f → %.2f K/D" % (prior["kd"], q["kd"])})
improved = rows(improved)

missing_note = ("%d returning players have no 2025 K/D on record and are not listed: "
                "%s. " % (len(unresolved), ", ".join(sorted(unresolved, key=str.lower)))
                if unresolved else "")

BALLOTS = [
    {
        "slug": "rookies",
        "title": "Best Rookie",
        "blurb": "First World Series, played like it wasn't. The Asani award.",
        "criteria": [
            "Played Philly 2026",
            "Their name does not appear on a 2025 roster",
            "Their SteamID does not appear on a 2025 roster either",
            "Sorted by team, then by name",
        ],
        "how": ("Eligibility is a starting point, not a verdict. SteamID alone is not "
                "enough — people play on house machines under whatever account is to "
                "hand, so a returning player can turn up with an id 2025 never saw. "
                "Name alone is not enough either. A player is a rookie here only when "
                "both miss. Staff can add or remove anyone before voting opens."),
        "eligible": rookies,
        "counts": ["%d returning from 2025" % returned],
    },
    {
        "slug": "carry",
        "title": "Carry Us, Daddy",
        "blurb": "Held a team together on their back. The PDX award.",
        "criteria": [
            "Played Philly 2026",
            "Weekend K/D of at least %.1f" % MIN_KD,
            "K/D is weekend kills over weekend deaths, both days combined",
            "Minimum halves played: %d" % MIN_HALVES,
            "Sorted by team, then by name",
        ],
        "how": ("Carrying is not a statistic, so this shortlist is only who finished "
                "the weekend above water — the vote decides who was holding a team "
                "up. It is derived from the published board: change the stats and "
                "this list changes with them."),
        "eligible": carry,
        "counts": ["%d players on the 2026 board" % len(agg)],
    },
    {
        "slug": "losing",
        "title": "Best On A Losing Team",
        "blurb": "The performance that deserved a better result.",
        "criteria": [
            "Played Philly 2026",
            "Weekend K/D of at least %.1f" % MIN_KD,
            "Not on %s — they won it, so nobody there was on a losing team"
            % LOSING_EXCLUDE,
            "Minimum halves played: %d" % MIN_HALVES,
            "Sorted by team, then by name",
        ],
        "how": ("The same floor as Carry Us with the winning company struck out. "
                "Losing here means the weekend, not a single match — a company that "
                "lost the final still lost it."),
        "eligible": losing,
        "counts": ["%d struck out on %s" % (len(carry) - len(losing), LOSING_EXCLUDE)],
    },
    {
        "slug": "improved",
        "title": "Most Improved",
        "blurb": "Turned up a different player to last year.",
        "criteria": [
            "Played Philly 2025 and Philly 2026",
            "2026 weekend K/D higher than their 2025 K/D, by more than %.2f" % MIN_GAIN,
            "2025 K/D is group stage and playoffs combined, from Jane's workbook",
            "Matched across years by SteamID on the 2025 roster, then by name",
            "Sorted by team, then by name",
        ],
        "how": ("The one vote category the numbers can narrow. %d players were at "
                "both LANs and %d of them improved. %sThe 2025 workbook records no "
                "SteamIDs, so the link to a 2025 K/D is the roster name — where the "
                "board used a different name to the roster and nothing corroborates "
                "the pair, the player is left off rather than guessed at."
                % (both, len(improved), missing_note)),
        "eligible": improved,
        "counts": ["%d played both LANs" % both],
    },
]

# The decided and single-match sections were built by a MySQL-backed script and
# carry the same tagged names. Re-deriving them needs the data server; renaming
# them does not, so the fix is applied here rather than left to rot until the
# next full rebuild. Only "who" — "as" is the alias a performance was recorded
# under and is meant to differ.
# Both reductions, not just the current one: those rows were written under an
# earlier naming rule, so the string to replace is one this rule no longer
# produces. A name that is somebody's own is never a key -- two accounts can
# reduce to the same string, and renaming on a collision would rewrite a real
# player into another.
canonical = {q["who"] for q in agg.values()}
rename = {}
for steam, q in agg.items():
    for n in aliases.get(steam) or []:
        for was in (short(n), trim_flair(short(n))):
            if was != q["who"] and was not in canonical:
                rename.setdefault(was, set()).add(q["who"])
rename = {k: v.pop() for k, v in rename.items() if len(v) == 1}


def relabel(node):
    if isinstance(node, list):
        return [relabel(x) for x in node]
    if isinstance(node, dict):
        out = {k: relabel(v) for k, v in node.items()}
        if isinstance(out.get("who"), str) and out["who"] in rename:
            out["who"] = rename[out["who"]]
        return out
    return node


for section in ("decided", "single_match", "positions"):
    if section in awards:
        awards[section] = relabel(awards[section])

awards["ballots"] = [dict(b, status="proposed") for b in BALLOTS]
awards.pop("ballot", None)
awards["vote"] = [{"slug": b["slug"], "title": b["title"], "blurb": b["blurb"],
                   "status": "proposed"} for b in BALLOTS]

json.dump(awards, open(os.path.join(BASE, "awards.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# The stats board derives its own display names from a team-wide prefix, which
# strips the clan tag and nothing else -- so it showed the shoutout people hang
# off the back of a name ("mogers ＃ky", "cory 4 rdk,jkimbro,liah"). Deriving it
# there again in JS would be a second naming rule to keep in step with this one.
# Ship the answer instead: the board looks a row up here and falls back to its
# own derivation for anything absent, which is every 2025 name. The full in-game
# name stays on the row's title attribute, so nothing is lost.
names = {}
for day in stats["days"].values():
    for p in day["players"]:
        who = agg[p["steam_id"]]["who"]
        if p["name"] != who:
            names[p["name"]] = who

# The page is self-contained -- no fetch -- so these only reach a reader through
# the embedded blocks. Writing the files without re-embedding them leaves the
# two silently disagreeing, which is why this is not a second step.
PROTO = os.path.join(os.path.dirname(BASE), "design", "prototype.html")
html = open(PROTO, encoding="utf-8").read()
for block_id, payload in (("awards-data", awards), ("player-names", names)):
    block = ('<script id="%s" type="application/json">%s</script>'
             % (block_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
    pat = r'<script id="%s" type="application/json">.*?</script>' % block_id
    html, n = re.subn(pat, lambda m: block, html, count=1, flags=re.S)
    if not n:      # first run for a block that isn't in the page yet
        anchor = '<script id="editions" type="application/json">'
        assert anchor in html, "editions block not found in prototype.html"
        html = html.replace(anchor, block + "\n" + anchor, 1)
open(PROTO, "w", encoding="utf-8", newline="").write(html)
print("embedded awards-data + %d display names into design/prototype.html\n" % len(names))

for b in awards["ballots"]:
    print("%-9s %2d eligible   %s" % (b["slug"], len(b["eligible"]),
                                      " · ".join(b["counts"])))
print("\nreturning but no 2025 K/D on record: %d  (%s)"
      % (len(unresolved), ", ".join(sorted(unresolved, key=str.lower)) or "none"))
for b in awards["ballots"]:
    print("\n%s (%d)" % (b["title"], len(b["eligible"])))
    for r in b["eligible"]:
        print("   %-26s %-28s %s" % (r["name"], r["team"] or "—", r.get("note") or ""))
