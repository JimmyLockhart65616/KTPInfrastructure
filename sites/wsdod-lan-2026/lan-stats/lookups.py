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

# DODC_* — allies 1-8, axis 10-19, british 21-25. Names use the league's own
# vernacular where it has one (Stoss, Unter, Tommy, Scharf), because that is
# what a KTP player calls the class; the weapon is kept in parentheses so the
# mapping back to the enum stays obvious.
CLASS_NAMES: dict[int, str] = {
    1: "Garand", 2: "Carbine", 3: "Tommy (Thompson)", 4: "Grease Gun",
    5: "Springfield", 6: "BAR", 7: ".30 Cal", 8: "Bazooka",
    10: "K98", 11: "Stoss (K43)", 12: "Unter (MP40)", 13: "STG (MP44)",
    14: "Scharf (K98 scoped)", 15: "FG42", 16: "FG42 scoped",
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

# KTP's four playing positions, confirmed by the operator 2026-08-06. This is a
# league taxonomy, not the game's -- DoD has 25 classes and KTP fields four
# positions, so the mapping is deliberately lossy.
#
# ⚠️ It is also incomplete by construction: a 3rd often plays Garand, which is
# the same class id a Rifle plays. Spawns therefore CANNOT distinguish a 3rd on
# Garand from a Rifle, and the Tommy/Unter asymmetry in the LAN data shows it --
# 643 Tommy + 190 Carbine spawns against 3,290 Unter, because the Allied 3rd is
# usually on Garand. Treat class_role() as a hint; a player's real position is a
# roster fact, not something spawns can prove.
CLASS_ROLE: dict[int, str] = {
    1: "Rifle", 10: "Rifle",                    # Garand / K98
    6: "Heavy", 13: "Heavy",                    # BAR / STG
    2: "3rd", 3: "3rd", 11: "3rd", 12: "3rd",   # Carbine / Tommy / Stoss / Unter
    5: "Sniper", 14: "Sniper",                  # Springfield / Scharf
}

# Position is read from AXIS play, because only the Axis classes map one-to-one.
# On Allies a Garand is a Rifle OR a 3rd and a BAR is a Heavy OR a 3rd, so the
# Allied half of a match cannot distinguish them. Teams swap sides at halftime,
# so a player's Axis class settles what their Allied class hides -- all 61 LAN
# players played Axis, so nothing needed a roster.
AXIS_ROLE: dict[int, str] = {
    10: "Rifle", 11: "3rd", 12: "3rd", 13: "Heavy", 14: "Sniper",
}

# Positions in the order the league lists them, for stable table ordering.
ROLE_ORDER = ["Rifle", "Heavy", "3rd", "Sniper", "Other"]

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
    return dict(sorted(out.items(),
                       key=lambda kv: (ROLE_ORDER.index(kv[0])
                                       if kv[0] in ROLE_ORDER else 99, -kv[1])))


def primary_role(counts: dict) -> str:
    """The position a player filled, decided by their Axis class.

    Axis classes are one-to-one with positions; Allied ones are not. Falling
    back to overall spawn share when a player never played Axis is a guess and
    is marked as such by returning the share-based answer -- but at the 2026 LAN
    every player played both sides, so the fallback never fired.
    """
    axis = {}
    for k, v in counts.items():
        i = _as_int(k)
        if i in AXIS_ROLE:
            axis[AXIS_ROLE[i]] = axis.get(AXIS_ROLE[i], 0) + int(v)
    if axis:
        return max(axis, key=axis.get)

    rolled = {}
    for k, v in counts.items():
        rolled[class_role(k)] = rolled.get(class_role(k), 0) + int(v)
    rolled.pop("Other", None)
    return max(rolled, key=rolled.get) if rolled else "Other"


def label_hitboxes(boxes: dict) -> dict:
    out: dict[str, dict] = {}
    for k, v in boxes.items():
        name = hitbox_name(k)
        cur = out.setdefault(name, {"hits": 0, "damage": 0})
        cur["hits"] += int(v.get("hits", 0))
        cur["damage"] += int(v.get("damage", 0))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["hits"]))
