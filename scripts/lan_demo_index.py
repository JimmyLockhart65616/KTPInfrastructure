#!/usr/bin/env python3
"""Generate a styled, match-grouped browser for demos/LAN-PHILLY2026/.

nginx's autoindex is a flat list of filenames. Because `index index.html` applies to the
/demos location, dropping an index.html into a directory replaces that listing entirely --
so this changes the STRUCTURE, not just the colours: demos are grouped by match, both halves
on one row, teams and map named, sizes formatted.

Chrome (nav, sponsor pill, footer) is copied from support.ktpdod.com so these pages are the
same family as the rest of KTP. Token names keep their blue-era spelling on purpose --
`--blue` is moss green now, and every rule references those names.

Idempotent: only ever writes index.html, never touches a .dem. Safe to re-run.
Usage: lan_demo_index.py [--apply]
"""
import argparse, collections, csv, html, json, os, re

AR = "/opt/ktp-lan-archive/philly-2026"
ROOT = "/home/hltvserver/hlds/dod/demos/LAN-PHILLY2026"
TYPES = ["ktp", "scrim", "draft", "12man"]
TYPE_LABEL = {"ktp": "League (.ktp)", "scrim": "Scrims", "draft": "Drafts", "12man": "12-man"}

CSS = """
:root{
  --bg:#171c0a; --panel:#252a14; --panel-2:#323920; --inset:#101407; --border:#3d432b;
  --rule:rgba(61,67,43,0.5); --text:#eae7d4; --dim:#b6b299; --faint:#98947c;
  --red:#d0513b; --red-soft:#e07a63; --blue:#819746; --blue-soft:#9fb45c; --amber:#c08b5c;
  --radius:14px; --panel-grad:linear-gradient(180deg,var(--panel) 0%,#1e230f 100%);
  --mono:"JetBrains Mono",ui-monospace,"Cascadia Code",Consolas,Menlo,monospace;
  color-scheme:dark;
}
*{margin:0;padding:0;box-sizing:border-box}
/* Reserve the scrollbar gutter ALWAYS. Without it a short page (no scrollbar) is ~15px
   wider than a long one, so centred content — including the header — shifts sideways
   as you move between pages. That was measured at 7px on the LAN root page. */
html{scrollbar-gutter:stable}
body{background:radial-gradient(120% 80% at 50% -10%,#252a14 0%,rgba(37,42,20,0) 55%),var(--bg);
  background-attachment:fixed;color:var(--text);font-family:var(--mono);font-size:15px;
  line-height:1.55;-webkit-font-smoothing:antialiased;min-height:100vh}
a{color:var(--blue);text-decoration:none}
a:hover{color:var(--blue-soft)}
code{font-family:var(--mono);color:var(--blue-soft)}
::selection{background:var(--red);color:#150b04}
a:focus-visible{outline:2px solid var(--blue-soft);outline-offset:2px}
/* 1180 and 15px are shared with ktp-fastdl-indexes.py and the landing page — a different
   value here slides the header sideways as you move between pages. */
.wrap{max-width:1180px;margin:0 auto;padding:0 22px;width:100%}
.mt8{margin-top:8px}
/* .card/.match set display, which beats the UA [hidden] rule */
[hidden]{display:none!important}
.search{display:flex;align-items:center;gap:.7rem;margin:0 0 1.1rem;flex-wrap:wrap}
.search input{flex:1 1 240px;min-width:0;max-width:420px;background:var(--inset);
  border:1px solid var(--border);border-radius:999px;padding:.45rem .95rem;color:var(--text);
  font-family:var(--mono);font-size:.84rem}
.search input:focus{outline:none;border-color:var(--blue)}
.search input::placeholder{color:var(--faint)}
.qc{color:var(--faint);font-size:.76rem;white-space:nowrap}
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
.match{background:var(--panel-grad);border:1px solid var(--border);border-radius:var(--radius);
  padding:.75rem .95rem;margin-bottom:.6rem}
.match:hover{border-color:var(--blue)}
.mh{display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline;justify-content:space-between}
.teams{font-weight:700;letter-spacing:.2px}
.vs{color:var(--faint);font-weight:400;padding:0 .35rem}
.meta{color:var(--faint);font-size:.76rem}
.files{margin-top:.55rem;display:flex;flex-wrap:wrap;gap:.4rem}
.f{display:inline-flex;align-items:center;gap:.45rem;background:var(--inset);
  border:1px solid var(--rule);border-radius:8px;padding:.24rem .6rem;font-size:.78rem}
.f:hover{border-color:var(--blue)}
.f .h{color:var(--red-soft);font-weight:700}
.f .sz{color:var(--faint)}
footer{border-top:1px solid var(--border);padding:32px 0 72px;color:var(--dim);
  font-size:0.82rem;margin-top:48px}
footer.split{display:flex;flex-wrap:wrap;gap:24px;justify-content:space-between}
footer .col{max-width:46ch}
footer h4{color:var(--text);font-size:0.72rem;letter-spacing:1.6px;text-transform:uppercase;margin-bottom:8px}
footer p{margin:4px 0}
footer .accent{color:var(--red);white-space:nowrap}
"""

NAV = (
  '<nav>\n  <div class="wrap row">\n'
  '    <span class="brand"><span class="k">KTP</span> &mdash; Demo Archive</span>\n'
  '    <span class="spacer"></span>\n'
  '    <a class="navlink hidesm" href="https://fastdl.ktpdod.com/">Downloads</a>\n'
  '    <a class="navlink hidesm" href="https://fastdl.ktpdod.com/demos/">Demos</a>\n'
  '    <a class="navlink hidesm" href="https://netcode.ktpdod.com/">Netcode</a>\n'
  '    <a class="navlink hidesm" href="https://profiles.ktpdod.com/">Profiles</a>\n'
  '    <a class="navlink hidesm" href="https://bundles.ktpdod.com/">My Data</a>\n'
  '    <a class="navlink hidesm" href="https://ac.ktpdod.com/">Anti-Cheat</a>\n'
  '    <a class="navlink" href="https://support.ktpdod.com">Support</a>\n'
  '  </div>\n</nav>\n')

EYEBROW = ('<div class="eyebrow">Keep the Practice &middot; Competitive Day of Defeat'
           '<a class="sponsor-slot" href="https://github.com/sponsors/afraznein">'
           '&#10084; Sponsor KTP</a></div>\n')

FOOTER = (
  '<footer class="split">\n'
  '  <div class="col">\n'
  '    <h4>What this is</h4>\n'
  '    <p>Every match recorded at WSDoD Philly 2026, hardlinked from the verified event\n'
  '      archive &mdash; 1,863 demos, md5-checked against source. Excluded from retention.</p>\n'
  '  </div>\n'
  '  <div class="col">\n'
  '    <h4>Keep it running</h4>\n'
  '    <p><a href="https://github.com/sponsors/afraznein">Sponsor the infrastructure</a> &middot;\n'
  '      <a href="https://support.ktpdod.com">Report a problem</a></p>\n'
  '    <p class="mt8"><span class="accent">Keep the Practice</span></p>\n'
  '  </div>\n'
  '</footer>\n')


SEARCH = ('<div class="search">'
          '<input id="q" type="search" placeholder="Filter this page&hellip;" autocomplete="off"'
          ' spellcheck="false" aria-label="Filter this page" aria-controls="qc">'
          '<span id="qc" class="qc" role="status" aria-live="polite"></span></div>'
          '<p id="qnone" class="note" hidden>Nothing on this page matches that filter.</p>')

SCRIPT = """<script>
(function(){
  var q=document.getElementById('q'); if(!q) return;
  var items=[].slice.call(document.querySelectorAll('[data-s]'));
  var heads=[].slice.call(document.querySelectorAll('h2'));
  var cnt=document.getElementById('qc'), none=document.getElementById('qnone');
  function apply(){
    var terms=q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    var shown=0;
    items.forEach(function(el){
      var s=el.getAttribute('data-s');
      var ok=terms.every(function(w){return s.indexOf(w)!==-1;});
      el.hidden=!ok; if(ok) shown++;
    });
    heads.forEach(function(h){
      var n=h.nextElementSibling, any=false;
      while(n && n.tagName!=='H2'){
        if(n.hasAttribute('data-s')){ if(!n.hidden) any=true; }
        else if(n.querySelector('[data-s]:not([hidden])')) any=true;
        n=n.nextElementSibling;
      }
      h.hidden = terms.length>0 && !any;
    });
    cnt.textContent = terms.length ? shown+' of '+items.length+' shown'
                                   : items.length+(items.length===1?' item':' items');
    none.hidden = !(terms.length>0 && shown===0);
  }
  q.addEventListener('input',apply);
  apply();
})();
</script>"""


def human(n):
    v = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if v < 1024 or u == "GB":
            return ("%.1f %s" % (v, u)) if u == "GB" else ("%.0f %s" % (v, u))
        v /= 1024.0


# Root-relative nav hrefs 404 on netcode/profiles/bundles, which each have their own docroot.
# That was fixed on 2026-07-17 and regressed twice, so it is asserted rather than remembered.
def _nav(markup):
    hrefs = re.findall(r'class="navlink[^"]*" href="([^"]+)"', markup)
    bad = [h for h in hrefs if not h.startswith("http")]
    assert hrefs and not bad, "nav href must be absolute, got %s" % (bad or "no navlinks")
    return markup

def page(title, body):
    parts = [
      '<!DOCTYPE html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
      '<meta name="viewport" content="width=device-width, initial-scale=1">',
      '<meta name="color-scheme" content="dark">',
      '<meta name="theme-color" content="#171c0a">',
      '<meta name="robots" content="noindex, nofollow">',
      '<link rel="icon" href="/favicon.ico">',
      '<title>' + html.escape(title) + '</title>',
      '<style>' + CSS + '</style>', '</head>', '<body>',
      _nav(NAV), '<div class="wrap">', EYEBROW, body, FOOTER, '</div>', SCRIPT, '</body></html>', '']
    return "\n".join(parts)


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

windows = {m["id"]: m for m in json.load(open(AR + "/match_windows.json"))}
byid = {r["match_id"]: r for r in csv.DictReader(open(AR + "/match_index.csv"))}

written, counts = [], {}
for mt in TYPES:
    d = os.path.join(ROOT, mt)
    if not os.path.isdir(d):
        continue
    files = sorted(f for f in os.listdir(d) if f.endswith(".dem"))
    counts[mt] = len(files)

    groups = collections.OrderedDict()
    for f in files:
        m = re.search(r"(\d{10}-KTP\d+)", f)
        groups.setdefault(m.group(1) if m else "unknown", []).append(f)

    cards = []
    for mid, fl in sorted(groups.items(), key=lambda kv: kv[0]):
        r = byid.get(mid, {})
        w = windows.get(mid, {})
        tm = re.match(r"[^_]+_[^_]+_h\d_([A-Za-z0-9]+)_([A-Za-z0-9]+)_", sorted(fl)[0])
        if tm:
            teams = ('<span class="teams">' + html.escape(tm.group(1))
                     + '<span class="vs">vs</span>' + html.escape(tm.group(2)) + '</span>')
        else:
            teams = '<span class="teams">' + html.escape(mid) + '</span>'
        bits = [x for x in (r.get("map", "") or w.get("map", ""), r.get("start", ""),
                            r.get("score", "") or w.get("score", "")) if x]
        meta = html.escape(" · ".join(bits))
        chips = []
        for f in sorted(fl):
            hm = re.search(r"_(h\d)[_-]", f)
            lbl = hm.group(1) if hm else "dem"
            pm = re.search(r"_part(\d)", f)
            lbl += ("·p" + pm.group(1)) if pm else ""
            chips.append('<a class="f" href="' + html.escape(f) + '"><span class="h">'
                         + lbl + '</span><span class="sz">'
                         + human(os.path.getsize(os.path.join(d, f))) + '</span></a>')
        key = " ".join([mid, meta] + ([tm.group(1), tm.group(2)] if tm else [])
                       + sorted(fl)).lower()
        cards.append('<div class="match" data-s="' + html.escape(key, quote=True)
                     + '"><div class="mh">' + teams
                     + '<span class="meta">' + meta + '</span></div>'
                     + '<div class="files">' + "".join(chips) + '</div></div>')

    body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / '
            '<a href="/demos/LAN-PHILLY2026/">LAN-PHILLY2026</a> / ' + mt + '</div>'
            + '<h1>WSDoD Philly 2026 &mdash; <span class="accent">'
            + html.escape(TYPE_LABEL.get(mt, mt)) + '</span></h1>'
            + '<p class="lede">' + str(len(files)) + ' demos across ' + str(len(groups))
            + ' matches. Named <code>type_matchid_half_team1_team2_map</code>.</p>'
            + SEARCH + "".join(cards))
    written.append((os.path.join(d, "index.html"), page("Philly 2026 — " + mt, body)))

cards = []
for mt in TYPES:
    if mt in counts:
        cards.append('<div class="match" data-s="'
                     + html.escape((mt + " " + TYPE_LABEL.get(mt, mt)).lower(), quote=True)
                     + '"><div class="mh">'
                     '<span class="teams"><a href="' + mt + '/">'
                     + html.escape(TYPE_LABEL.get(mt, mt)) + '</a></span>'
                     '<span class="meta">' + str(counts[mt]) + ' demos</span></div></div>')
body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / '
        'LAN-PHILLY2026</div>'
        '<h1>WSDoD <span class="accent">Philly 2026</span></h1>'
        '<p class="lede">Every recorded match from the event, grouped by match and named by '
        'team. ' + str(sum(counts.values())) + ' demos total.</p>' + "".join(cards))
written.append((os.path.join(ROOT, "index.html"), page("WSDoD Philly 2026 — demos", body)))

print("index pages: %d | counts: %s" % (len(written), counts))
if args.apply:
    for p, b in written:
        open(p, "w", encoding="utf-8", newline="\n").write(b)
        os.chmod(p, 0o644)
    print("written.")
else:
    print("DRY RUN — nothing written.")
