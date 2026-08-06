#!/usr/bin/env python3
"""Generate styled index pages for /dod (client downloads) and the fleet demo tree.

Same approach as the LAN archive: `index index.html` means a generated index.html replaces
nginx's autoindex, so these get real structure instead of a flat file list.

Two very different trees:
  /dod            static game assets, 1.3 GB. Clients fetch by direct path and never read a
                  directory listing, so a landing page here is purely for humans. Only the top
                  level is generated -- nobody hand-browses /dod/maps/.
  /demos/<SRV>/   the fleet archive, ~11 new demos a day. MUST be regenerated on a schedule or
                  it goes stale; hooked into the 04:00 organizer cron.

LAN-PHILLY2026 is skipped -- it has its own generator that knows the team names.

Idempotent: only ever writes index.html. Usage: fastdl_indexes.py [--apply]
"""
import argparse, collections, html, os, re

FASTDL = "/var/www/fastdl"
DEMOS = "/home/hltvserver/hlds/dod/demos"
SKIP = {"LAN-PHILLY2026"}
CITY = {"ATL": "Atlanta", "DAL": "Dallas", "DEN": "Denver", "NY": "New York", "CHI": "Chicago"}
TYPE_LABEL = {"ktp": "League (.ktp)", "scrim": "Scrims", "draft": "Drafts", "12man": "12-man"}
RETENTION = {"ktp": "180 days", "draft": "180 days", "12man": "90 days", "scrim": "90 days"}

CSS = """
:root{--bg:#171c0a;--panel:#252a14;--inset:#101407;--border:#3d432b;
--rule:rgba(61,67,43,0.5);--text:#eae7d4;--dim:#b6b299;--faint:#98947c;
--red:#d0513b;--red-soft:#e07a63;--blue:#819746;--blue-soft:#9fb45c;--radius:14px;
--panel-grad:linear-gradient(180deg,var(--panel) 0%,#1e230f 100%);
--mono:"JetBrains Mono",ui-monospace,"Cascadia Code",Consolas,Menlo,monospace;color-scheme:dark}
*{margin:0;padding:0;box-sizing:border-box}
body{background:radial-gradient(120% 80% at 50% -10%,#252a14 0%,rgba(37,42,20,0) 55%),var(--bg);
background-attachment:fixed;color:var(--text);font-family:var(--mono);font-size:14px;
line-height:1.55;-webkit-font-smoothing:antialiased;min-height:100vh}
a{color:var(--blue);text-decoration:none}a:hover{color:var(--blue-soft)}
code{font-family:var(--mono);color:var(--blue-soft)}
::selection{background:var(--red);color:#150b04}
a:focus-visible{outline:2px solid var(--blue-soft);outline-offset:2px}
.wrap{max-width:1100px;margin:0 auto;padding:0 22px;width:100%}
.mt8{margin-top:8px}
nav{border-bottom:1px solid var(--border);background:rgba(16,20,7,0.72);position:static}
nav .row{display:flex;align-items:center;gap:22px;height:58px}
.brand{font-weight:800;letter-spacing:1px;font-size:1.05rem;color:var(--text)}
.brand .k{color:var(--red)}
nav .spacer{flex:1}
nav .navlink{color:var(--dim);font-size:0.82rem;letter-spacing:0.6px}
nav .navlink:hover{color:var(--text)}
@media (max-width:720px){nav .hidesm{display:none}}
.eyebrow{font-size:0.72rem;letter-spacing:2.4px;text-transform:uppercase;color:var(--dim);
display:flex;align-items:center;gap:10px;margin-top:34px}
.eyebrow::before{content:"";width:26px;height:2px;background:var(--blue);display:inline-block;flex:none}
.accent{color:var(--red)}
.sponsor-slot{margin-left:auto;font-size:0.72rem;font-weight:700;letter-spacing:0.4px;
color:var(--red-soft);border:1px solid var(--red);border-radius:999px;padding:4px 13px;
white-space:nowrap;text-transform:none}
.sponsor-slot:hover{background:var(--red);color:#150b04}
h1{font-size:clamp(1.5rem,3.4vw,2.1rem);font-weight:800;letter-spacing:-.6px;margin:14px 0 8px}
.lede{color:var(--dim);max-width:70ch;font-size:.9rem;margin-bottom:1.4rem}
.crumb{color:var(--faint);font-size:.78rem;margin:1.1rem 0 .2rem}
h2{font-size:.74rem;text-transform:uppercase;letter-spacing:1.4px;color:var(--faint);
margin:1.8rem 0 .7rem;padding-bottom:.35rem;border-bottom:1px solid var(--rule)}
.row2{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:.6rem}
.card{display:block;background:var(--panel-grad);border:1px solid var(--border);
border-radius:var(--radius);padding:.8rem .95rem;transition:border-color .15s ease,transform .15s ease}
.card:hover{border-color:var(--blue);transform:translateY(-1px)}
.card .t{color:var(--text);font-weight:700;letter-spacing:.3px}
.card .d{color:var(--faint);font-size:.78rem;margin-top:.25rem}
.match{background:var(--panel-grad);border:1px solid var(--border);border-radius:var(--radius);
padding:.7rem .9rem;margin-bottom:.55rem}
.match:hover{border-color:var(--blue)}
.mh{display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline;justify-content:space-between}
.teams{font-weight:700}
.meta{color:var(--faint);font-size:.76rem}
.files{margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.4rem}
.f{display:inline-flex;align-items:center;gap:.45rem;background:var(--inset);
border:1px solid var(--rule);border-radius:8px;padding:.24rem .6rem;font-size:.78rem}
.f:hover{border-color:var(--blue)}
.f .h{color:var(--red-soft);font-weight:700}.f .sz{color:var(--faint)}
.note{color:var(--faint);font-size:.78rem;margin:.2rem 0 1rem}
footer{border-top:1px solid var(--border);padding:32px 0 72px;color:var(--dim);
font-size:0.82rem;margin-top:48px}
footer.split{display:flex;flex-wrap:wrap;gap:24px;justify-content:space-between}
footer .col{max-width:46ch}
footer h4{color:var(--text);font-size:0.72rem;letter-spacing:1.6px;text-transform:uppercase;margin-bottom:8px}
footer p{margin:4px 0}
footer .accent{color:var(--red);white-space:nowrap}
"""

def nav(site):
    return ('<nav>\n  <div class="wrap row">\n'
            '    <span class="brand"><span class="k">KTP</span> &mdash; ' + site + '</span>\n'
            '    <span class="spacer"></span>\n'
            '    <a class="navlink hidesm" href="/">Downloads</a>\n'
            '    <a class="navlink hidesm" href="/demos/">Demos</a>\n'
            '    <a class="navlink hidesm" href="/netcode/">Netcode</a>\n'
            '    <a class="navlink hidesm" href="/anticheat/">Anti-Cheat</a>\n'
            '    <a class="navlink" href="https://support.ktpdod.com">Support</a>\n'
            '  </div>\n</nav>\n')

EYEBROW = ('<div class="eyebrow">Keep the Practice &middot; Competitive Day of Defeat'
           '<a class="sponsor-slot" href="https://github.com/sponsors/afraznein">'
           '&#10084; Sponsor KTP</a></div>\n')

def footer(what):
    return ('<footer class="split">\n  <div class="col">\n    <h4>What this is</h4>\n    <p>'
            + what + '</p>\n  </div>\n  <div class="col">\n    <h4>Keep it running</h4>\n'
            '    <p><a href="https://github.com/sponsors/afraznein">Sponsor the infrastructure</a> '
            '&middot;\n      <a href="https://support.ktpdod.com">Report a problem</a></p>\n'
            '    <p class="mt8"><span class="accent">Keep the Practice</span></p>\n'
            '  </div>\n</footer>\n')

def page(title, site, body, what):
    return "\n".join([
      '<!DOCTYPE html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
      '<meta name="viewport" content="width=device-width, initial-scale=1">',
      '<meta name="color-scheme" content="dark">',
      '<meta name="theme-color" content="#171c0a">',
      '<meta name="robots" content="noindex, nofollow">',
      '<link rel="icon" href="/favicon.ico">',
      '<title>' + html.escape(title) + '</title>',
      '<style>' + CSS + '</style>', '</head>', '<body>',
      nav(site), '<div class="wrap">', EYEBROW, body, footer(what), '</div>',
      '</body></html>', ''])

def human(n):
    v = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if v < 1024 or u == "GB":
            return ("%.1f %s" % (v, u)) if u == "GB" else ("%.0f %s" % (v, u))
        v /= 1024.0

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()
out = []

# ---------------------------------------------------------------- /dod
DOD_GROUPS = [
    ("Maps and terrain", ["maps", "overviews", "gfx"]),
    ("Models and sprites", ["models", "sprites"]),
    ("Sound", ["sound", "media"]),
    ("Configs and scripts", ["configs", "addons", "cl_dlls", "dlls", "events", "scripts"]),
]
present = {d for d in os.listdir(FASTDL + "/dod") if os.path.isdir(FASTDL + "/dod/" + d)}
cards = []
for label, dirs in DOD_GROUPS:
    have = [d for d in dirs if d in present]
    if not have:
        continue
    cards.append('<h2>' + label + '</h2><div class="row2">' + "".join(
        '<a class="card" href="' + d + '/"><div class="t">' + d + '/</div>'
        '<div class="d">' + str(len(os.listdir(FASTDL + "/dod/" + d))) + ' entries</div></a>'
        for d in have) + '</div>')
loose = sorted(f for f in os.listdir(FASTDL + "/dod") if os.path.isfile(FASTDL + "/dod/" + f))
body = ('<div class="crumb"><a href="/">fastdl</a> / dod</div>'
        '<h1>Client <span class="accent">download</span> files</h1>'
        '<p class="lede">These are the files your client pulls automatically when it joins a KTP '
        'server &mdash; maps, textures, models, sounds. <b>You do not need to download anything '
        'here by hand.</b> The list is browsable if you want to fetch one file directly.</p>'
        '<p class="note">' + str(len(present)) + ' directories, ' + str(len(loose))
        + ' loose files. Served over HTTP as <code>sv_downloadurl</code>.</p>'
        + "".join(cards)
        + '<h2>Other directories</h2><div class="row2">' + "".join(
            '<a class="card" href="' + d + '/"><div class="t">' + d + '/</div></a>'
            for d in sorted(present - {x for _, ds in DOD_GROUPS for x in ds})) + '</div>')
out.append((FASTDL + "/dod/index.html",
            page("KTP FastDL — client downloads", "Client Downloads", body,
                 "Fast content distribution for KTP game servers. Your client fetches from here on "
                 "connect, so joining a server never means hunting for a map pack.")))

# ---------------------------------------------------------------- /demos fleet
servers = sorted(d for d in os.listdir(DEMOS) if os.path.isdir(DEMOS + "/" + d))
by_city = collections.OrderedDict()
for s in servers:
    if s in SKIP:
        continue
    m = re.match(r"([A-Z]+)\d+$", s)
    by_city.setdefault(CITY.get(m.group(1), "Other") if m else "Other", []).append(s)

def count_dems(p):
    n = 0
    for root, _, fs in os.walk(p):
        n += sum(1 for f in fs if f.endswith(".dem"))
    return n

sections = []
lan = DEMOS + "/LAN-PHILLY2026"
if os.path.isdir(lan):
    sections.append('<h2>Event archive</h2><div class="row2">'
                    '<a class="card" href="LAN-PHILLY2026/"><div class="t">WSDoD Philly 2026</div>'
                    '<div class="d">' + str(count_dems(lan)) + ' demos &middot; kept indefinitely'
                    '</div></a></div>')
for city, srvs in by_city.items():
    sections.append('<h2>' + city + '</h2><div class="row2">' + "".join(
        '<a class="card" href="' + s + '/"><div class="t">' + s + '</div>'
        '<div class="d">' + str(count_dems(DEMOS + "/" + s)) + ' demos</div></a>'
        for s in srvs) + '</div>')
body = ('<div class="crumb"><a href="/">fastdl</a> / demos</div>'
        '<h1>Demo <span class="accent">archive</span></h1>'
        '<p class="lede">Every match HLTV records across the 24-server fleet, sorted by server and '
        'match type. <b>League and draft matches are kept 180 days; pickups and scrims 90.</b> '
        'Download one before it ages out.</p>' + "".join(sections))
out.append((DEMOS + "/index.html",
            page("KTP Demo Archive", "Demo Archive", body,
                 "Every competitive match on the KTP fleet, recorded by HLTV and kept on a "
                 "per-type retention schedule.")))

# ---------------------------------------------------------------- per server / per type
for s in servers:
    if s in SKIP:
        continue
    sp = DEMOS + "/" + s
    types = sorted(t for t in os.listdir(sp) if os.path.isdir(sp + "/" + t))
    body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / ' + s + '</div>'
            '<h1>' + s + ' <span class="accent">demos</span></h1>'
            '<p class="lede">Recorded matches on ' + s + ', by match type.</p>'
            '<div class="row2">' + "".join(
              '<a class="card" href="' + t + '/"><div class="t">'
              + html.escape(TYPE_LABEL.get(t, t)) + '</div><div class="d">'
              + str(count_dems(sp + "/" + t)) + ' demos &middot; kept '
              + RETENTION.get(t, "90 days") + '</div></a>' for t in types) + '</div>')
    out.append((sp + "/index.html", page("KTP demos — " + s, "Demo Archive", body,
                "Every competitive match on the KTP fleet, recorded by HLTV.")))

    for t in types:
        tp = sp + "/" + t
        files = sorted(f for f in os.listdir(tp) if f.endswith(".dem"))
        groups = collections.OrderedDict()
        for f in files:
            m = re.search(r"([\w.\-]+?)-(?:[A-Z]+\d+)(?:_h\d)?-\d{10}-", f)
            groups.setdefault(m.group(1).split("_", 1)[-1] if m else f, []).append(f)
        cards = []
        for mid, fl in groups.items():
            first = sorted(fl)[0]
            mp = re.search(r"-\d{10}-(.+?)(?:_part\d)?\.dem$", first)
            chips = []
            for f in sorted(fl):
                hm = re.search(r"_(h\d)-", f)
                pm = re.search(r"_part(\d)", f)
                lbl = (hm.group(1) if hm else "dem") + (("·p" + pm.group(1)) if pm else "")
                chips.append('<a class="f" href="' + html.escape(f) + '"><span class="h">' + lbl
                             + '</span><span class="sz">'
                             + human(os.path.getsize(tp + "/" + f)) + '</span></a>')
            cards.append('<div class="match"><div class="mh"><span class="teams">'
                         + html.escape(mid) + '</span><span class="meta">'
                         + html.escape(mp.group(1) if mp else "") + '</span></div>'
                         '<div class="files">' + "".join(chips) + '</div></div>')
        body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / '
                '<a href="/demos/' + s + '/">' + s + '</a> / ' + t + '</div>'
                '<h1>' + s + ' &mdash; <span class="accent">'
                + html.escape(TYPE_LABEL.get(t, t)) + '</span></h1>'
                '<p class="lede">' + str(len(files)) + ' demos in ' + str(len(groups))
                + ' matches. Kept ' + RETENTION.get(t, "90 days")
                + ' from recording, then deleted.</p>' + "".join(cards))
        out.append((tp + "/index.html", page("KTP demos — " + s + " " + t, "Demo Archive", body,
                    "Every competitive match on the KTP fleet, recorded by HLTV.")))

print("index pages: %d" % len(out))
if args.apply:
    for p, b in out:
        open(p, "w", encoding="utf-8", newline="\n").write(b)
        os.chmod(p, 0o644)
    print("written.")
else:
    for p, _ in out[:6]:
        print("   " + p)
    print("   ... (%d more)" % max(0, len(out) - 6))
    print("DRY RUN — nothing written.")
