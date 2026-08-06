"""DoD class and hitbox id -> name.

Both taken from source in this tree, not from memory or a wiki:

  classes  KTPAMXX/plugins/include/dodconst.inc  (enum DODC_*)
  hitboxes KTPhlsdk/dlls/monsters.h              (#define HITGROUP_*)

The class enum is sparse on purpose -- the mortar classes are commented out
upstream, which is why 9 and 20 are absent and the ranges restart at 10 and 21.
Anything not listed renders as "class N" rather than silently becoming
"unknown", so a new id shows up as itself instead of disappearing into a bucket.
"""

from __future__ import annotations

# DODC_* — allies 1-8, axis 10-19, british 21-25.
CLASS_NAMES: dict[int, str] = {
    1: "Rifleman (Garand)", 2: "Carbine", 3: "Thompson", 4: "Grease Gun",
    5: "Sniper (Springfield)", 6: "BAR", 7: ".30 Cal", 8: "Bazooka",
    10: "Kar98", 11: "K43", 12: "MP40", 13: "MP44",
    14: "Scharfschütze (K98 scoped)", 15: "FG42", 16: "FG42 scoped",
    17: "MG34", 18: "MG42", 19: "Panzerjäger",
    21: "Enfield", 22: "Sten", 23: "Marksman", 24: "Bren", 25: "PIAT",
}

CLASS_TEAM: dict[int, str] = {}
for _i in range(1, 9):
    CLASS_TEAM[_i] = "Allies"
for _i in range(10, 20):
    CLASS_TEAM[_i] = "Axis"
for _i in range(21, 26):
    CLASS_TEAM[_i] = "British"

# Broad role, for grouping a stats table without listing 25 weapons.
CLASS_ROLE: dict[int, str] = {
    1: "Rifle", 2: "Rifle", 10: "Rifle", 11: "Rifle", 21: "Rifle",
    3: "SMG", 4: "SMG", 12: "SMG", 22: "SMG",
    5: "Sniper", 14: "Sniper", 16: "Sniper", 23: "Sniper",
    6: "Support", 7: "MG", 13: "Support", 15: "Support",
    17: "MG", 18: "MG", 24: "MG",
    8: "Rocket", 19: "Rocket", 25: "Rocket",
}

# HITGROUP_* from the SDK.
HITBOX_NAMES: dict[int, str] = {
    0: "Generic", 1: "Head", 2: "Chest", 3: "Stomach",
    4: "Left arm", 5: "Right arm", 6: "Left leg", 7: "Right leg",
}


def _as_int(key) -> int | None:
    try:
        return int(key)
    except (TypeError, ValueError):
        return None


def class_name(key) -> str:
    i = _as_int(key)
    return CLASS_NAMES.get(i, "class %s" % key) if i is not None else str(key)


def class_role(key) -> str:
    i = _as_int(key)
    return CLASS_ROLE.get(i, "Other") if i is not None else "Other"


def class_team(key) -> str:
    i = _as_int(key)
    return CLASS_TEAM.get(i, "Unknown") if i is not None else "Unknown"


def hitbox_name(key) -> str:
    i = _as_int(key)
    return HITBOX_NAMES.get(i, "hitbox %s" % key) if i is not None else str(key)


def label_classes(counts: dict) -> dict:
    """{'14': 116} -> {'Scharfschütze (K98 scoped)': 116}, biggest first."""
    out: dict[str, int] = {}
    for k, v in counts.items():
        out[class_name(k)] = out.get(class_name(k), 0) + int(v)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def roll_up_roles(counts: dict) -> dict:
    out: dict[str, int] = {}
    for k, v in counts.items():
        out[class_role(k)] = out.get(class_role(k), 0) + int(v)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def label_hitboxes(boxes: dict) -> dict:
    out: dict[str, dict] = {}
    for k, v in boxes.items():
        name = hitbox_name(k)
        cur = out.setdefault(name, {"hits": 0, "damage": 0})
        cur["hits"] += int(v.get("hits", 0))
        cur["damage"] += int(v.get("damage", 0))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["hits"]))
