"""The `rating_methodology` season aggregate: how KTPR, MMR and momentum are
computed, with every variable and its current value, per map.

Published so the website can show it under Stats -- the equations, the
parameters, the sample each number was fitted on and how well it fit. The
numbers change as data lands (weekly refit), and this document changes with
them, so a reader always sees what the ratings on the site were actually
computed with.

It carries no player rows: nothing here is about anyone. Same publish path
as `mmr_openskill` (CI writes the file, the operator imports it).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # scripts/: ktpr_v2, analytics_report_dto
sys.path.insert(0, str(HERE.parents[1]))      # repo root: analytics_report_dto imports scripts.*

import analytics_report_dto as DTO             # noqa: E402
import ladder                                  # noqa: E402
import mmr_payload as MMRP                     # noqa: E402
import performance as PF                       # noqa: E402
from ktpr_v2 import KtprV2Config               # noqa: E402

AGGREGATE_KIND = "rating_methodology"
METHOD_VERSION = "rating_methodology_v1"
PARAMS = HERE / "momentum_params.json"

# Every number below is read from the code that uses it, never retyped, so
# this document cannot say one thing while the ratings do another.
_W = KtprV2Config()
_SCALE = {"center": int(DTO.KTPR_DISPLAY_CENTER), "scale": int(DTO.KTPR_DISPLAY_PER_Z), "floor": int(DTO.KTPR_DISPLAY_FLOOR)}
_INIT = ladder.OpenSkill().m.rating()

KTPR_V2 = {
    "name": "KTPR v2",
    "what": "Per-match performance rating. How well you played in this match, independent of who won.",
    "equation": "z = Σ w_c · z_c over the components available for the match; "
                "each z_c is the player's per-match z-score on that component "
                "(mean 0, spread 1 across the players in the match). "
                "A missing component's weight is redistributed over the rest.",
    "components": [
        {"name": "swing", "weight": _W.swing_weight,
         "what": "attributed flag swing: the flag-control probability your kills and caps moved"},
        {"name": "kast_f", "weight": _W.kast_weight,
         "what": "KAST-F: share of your lives with a kill, assist, survival or trade in a flag fight"},
        {"name": "output", "weight": _W.output_weight, "what": "damage per life / 100 + kill/death ratio"},
        {"name": "multikill", "weight": _W.multikill_weight, "what": "fast 2k + 2·fast 3k + 4·fast 4k+"},
    ],
    "display": {"equation": f"max({_SCALE['floor']}, {_SCALE['center']} + {_SCALE['scale']}·z)",
                "center": _SCALE["center"], "scale": _SCALE["scale"], "floor": _SCALE["floor"],
                "what": f"{_SCALE['center']} is the match average; {_SCALE['center'] + _SCALE['scale']} is one spread above it"},
    "status": "provisional",
}

MMR = {
    "name": "MMR (OpenSkill)",
    "what": "Cross-match skill rating. How likely your side is to win, learned from results across the season. "
            "Carries an uncertainty that shrinks with matches played.",
    "model": "Plackett-Luce (openskill 6.2.0), two teams, each player's rating updated by the match result",
    "initial": {"mu": round(_INIT.mu, 3), "sigma": round(_INIT.sigma, 3),
                "what": "everyone starts here; sigma is the uncertainty"},
    "displayed": {"rating": "mu", "uncertainty": "sigma", "conservative": "mu − 3·sigma",
                  "what": "conservative is the value you are very likely at least as good as"},
    "min_matches": MMRP.MIN_MATCHES_FOR_DISPLAY,
    "prediction": {
        "equation": "p_damped = 0.5 + (p − 0.5) · n / (n + k)",
        "k": ladder.EVIDENCE_K,
        "n": "the thinner side's mean matches played",
        "what": "a prediction between two barely-rated sides is pulled toward a coin flip; "
                "confidence is earned by evidence, not asserted by the model",
    },
    "performance_weighting": {
        "enabled": False, "strength": PF.DEFAULT_STRENGTH,
        "what": "when on, a side's rating change is split by each player's KTPR contribution "
                "instead of evenly. Off until measured to predict better than even splits.",
    },
    "status": "provisional",
}

MOMENTUM = {
    "name": "Momentum credit",
    "what": "Objective value traced back to the plays that enabled it. A 4k that leads to a cap "
            "and then a capout is paid part of that objective value, decaying with the lag.",
    "mechanism": [
        "Every momentum event (multikill, cap, capout) is both a payout and a deposit for its team's ledger.",
        "Payout: the event's value is split between the actor(s) and the team's outstanding deposits; "
        "the deposits' share at lag d is 1 − 1/lift(d).",
        "Deposit: the event enters the ledger and forwards a fraction rho of anything it is later paid "
        "to the deposits that fed it — the secondary assist.",
        "An enemy cap clears the ledger.",
        "Kills earn nothing here; KTPR already counts them. This is objective lift only.",
    ],
    "status": "research — not yet a KTPR component",
}


def _load_version_history(summary_path=None):
    """Load accumulated version history from weekly_summary.json files.

    Reads weekly summaries (generated by run_weekly.py) and builds a history array
    showing how accuracy/sample size have evolved. Returns [week_entry, ...] oldest first.
    """
    from datetime import datetime

    history = []
    summary_file = Path(summary_path) if summary_path else (HERE / "weekly_summary.json")
    if not summary_file.exists():
        return history

    try:
        data = json.loads(summary_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return history

    # Extract date and compute week number from generated_at (ISO 8601 timestamp)
    generated_at_str = data.get("generated_at", "")
    if not generated_at_str:
        return history

    try:
        dt = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
        # Week number: S10 starts 2026-09-13 (week 1), each Monday is a new week
        s10_start = datetime.fromisoformat("2026-09-13T00:00:00+00:00")
        days_since = (dt.date() - s10_start.date()).days
        week = (days_since // 7) + 1
        date_str = dt.date().isoformat()
    except (ValueError, AttributeError):
        return history

    # Build entry from current summary
    accuracy_pct = round(data.get("accuracy", 0) * 100, 1)
    completed_matches = data.get("completed_matches", 0)
    headline = data.get("headline", "")
    upsets = data.get("upsets", 0)

    # Compute upsets_pct if we have matches (upsets / completed_matches)
    upsets_pct = round((upsets / completed_matches * 100), 1) if completed_matches else 0

    entry = {
        "week": week,
        "date": date_str,
        "accuracy_pct": accuracy_pct,
        "completed_matches": completed_matches,
        "upsets": upsets,
        "upsets_pct": upsets_pct,
        "headline": headline,
    }
    history.append(entry)

    return history


def build(params, *, generated_at, source_report_count=0, report_schema_version=9, summary_path=None):
    """The payload. `params` is momentum_params.json as a dict.

    Args:
        params: momentum_params.json as a dict
        generated_at: ISO 8601 timestamp when this payload was built
        source_report_count: number of source match reports accumulated so far
        report_schema_version: schema version of the source reports
        summary_path: optional path to weekly_summary.json (for testing)
    """
    maps = {}
    for mp, m in sorted(params.get("maps", {}).items()):
        maps[mp] = {
            "sample": {k: m[k] for k in ("halves", "official_halves", "multikills", "caps", "capouts")},
            "momentum_curves": m["curves"] if m.get("curves") else {"uses": "pooled"},
            "scoring": m["scoring"] if m.get("scoring") else {"uses": "fallback",
                                                                "fallback": params["definitions"]["fallback"]["scoring"]},
        }

    version_history = _load_version_history(summary_path)

    return {
        "kind": AGGREGATE_KIND,
        "method_version": METHOD_VERSION,
        "generated_at": generated_at,
        "provisional": True,
        "notice": "All values are refit as matches land and may change week to week. "
                  "Sample sizes and fit quality are shown so the reader can judge each number.",
        "ktpr_v2": KTPR_V2,
        "mmr": MMR,
        "momentum": {
            **MOMENTUM,
            "definitions": params.get("definitions", {}),
            "fitted_at": params.get("generated_at"),
            "corpus": params.get("corpus", {}),
            "rho": params.get("rho", {}),
            "pooled_curves": params.get("pooled", {}),
            "maps": maps,
        },
        "version_history": version_history,
        "source_report_count": int(source_report_count),
        "report_schema_version": int(report_schema_version),
    }


def load_params(path=PARAMS):
    return json.loads(Path(path).read_text(encoding="utf-8"))


FORBIDDEN_KEYS = ("players", "player_id", "steam_id", "steam_id64", "alias")


def validate_for_import(payload):
    """Problems that should stop this payload being written. [] means fine."""
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    problems = []
    if payload.get("kind") != AGGREGATE_KIND:
        problems.append(f"kind is {payload.get('kind')!r}, expected {AGGREGATE_KIND!r}")
    for section in ("ktpr_v2", "mmr", "momentum"):
        if not isinstance(payload.get(section), dict):
            problems.append(f"missing section {section!r}")
    if not isinstance((payload.get("momentum") or {}).get("maps"), dict):
        problems.append("momentum.maps missing")
    body = json.dumps(payload)
    leaked = [k for k in FORBIDDEN_KEYS if f'"{k}"' in body]
    if leaked:
        problems.append(f"payload carries player-shaped keys {leaked}; this document is about nobody")
    return problems
