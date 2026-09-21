"""ktp-data-server-health.sh: the state file remembers two different dates.

The health check is the only thing that observes the transition, and its log is
root-only. Without `since` in the state file, "what is broken right now" could
be answered but "since when" could not -- which is how ktp-identity-reconcile
sat failed for over a week after its one alert.

`since` alone then answered the question wrong. It is a DETECTION date, and a
fault older than the run that first saw it reads as new: the same unit failed
2026-09-08 and was stamped 2026-09-17, the hour `systemctl --failed` became a
producer, so the weekly gate aged a 13-day outage at four days against a
three-day threshold. `fault_since` is the onset where something durable knows
one. Both builders are extracted from the shipped script by marker.
"""
import json
import os
import pathlib
import shlex
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BEGIN, END = "# >>> ktp-health-state", "# <<< ktp-health-state"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(
    shutil.which(BASH) is None or shutil.which("jq") is None, reason="needs bash and jq"
)


def source():
    text = SCRIPT.read_text(encoding="utf-8")
    assert BEGIN in text and END in text, "state markers are gone from the shipped script"
    return text.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]


def build(tmp_path, down, prev, detail, ts, fault=None):
    body = "%s\nhealth_state_document '%s' '%s' '%s' '%s' '%s'\n" % (
        source(), json.dumps(down), json.dumps(prev), json.dumps(detail), ts,
        json.dumps(fault or {}))
    p = tmp_path / "probe.sh"
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, p.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_new_item_is_stamped_now_and_carried_forward_unchanged(tmp_path):
    t1 = build(tmp_path, ["mysql.service=failed"], {}, {}, "2026-09-08 09:00:00")
    assert t1["since"] == {"mysql.service=failed": "2026-09-08 09:00:00"}
    t2 = build(tmp_path, ["mysql.service=failed"], t1, {}, "2026-09-16 11:00:00")
    assert t2["since"] == {"mysql.service=failed": "2026-09-08 09:00:00"}
    assert t2["updated_at"] == "2026-09-16 11:00:00"


def test_a_cleared_item_drops_out_of_since(tmp_path):
    prev = {"since": {"a": "2026-09-01 00:00:00", "b": "2026-09-02 00:00:00"}}
    doc = build(tmp_path, ["b"], prev, {}, "2026-09-03 00:00:00")
    assert doc["down"] == ["b"] and doc["since"] == {"b": "2026-09-02 00:00:00"}


def test_an_old_state_file_without_since_reads_as_since_now_once(tmp_path):
    """The shape written before this change: every current item stamps now.
    Wrong by up to one week for anything already down, right from then on."""
    doc = build(tmp_path, ["disk-growth:/"], {"updated_at": "x", "down": ["disk-growth:/"]}, {}, "2026-09-16 11:00:00")
    assert doc["since"] == {"disk-growth:/": "2026-09-16 11:00:00"}


def test_detail_rides_along_only_for_items_that_have_one(tmp_path):
    doc = build(tmp_path, ["disk-growth:/", "failed-unit:x.service"], {},
                {"disk-growth:/": "4 GiB/day over the last 12h+", "stale-key": "ignored"}, "t")
    assert doc["detail"] == {"disk-growth:/": "4 GiB/day over the last 12h+"}


def test_empty_down_set_is_a_valid_document(tmp_path):
    doc = build(tmp_path, [], {"since": {"gone": "t0"}}, {}, "t1")
    assert doc == {"updated_at": "t1", "down": [], "since": {},
                   "fault_since": {}, "detail": {}}


# --- fault_since: the onset, wherever something durable knows one -------------
# `since` answers "when did this check first see it", which is the only question
# the check can answer about itself. It is not the question a threshold wants.


def test_fault_since_is_absent_when_nothing_knows_better(tmp_path):
    """Sparse like `detail`. Absent, never null -- a consumer that finds no
    entry falls back to `since` instead of deciding what a null means."""
    doc = build(tmp_path, ["disk-growth:/"], {}, {}, "2026-09-17 01:17:03")
    assert doc["fault_since"] == {}


def test_a_probed_onset_back_dates_an_item_the_check_saw_late(tmp_path):
    """The measured case: the unit failed 09-08, the `failed-unit:` producer
    first ran 09-16, and the gate read four days for a thirteen-day outage."""
    item = "failed-unit:ktp-identity-reconcile.service"
    doc = build(tmp_path, [item], {}, {}, "2026-09-17 01:17:03",
                {item: "2026-09-08 09:01:53"})
    assert doc["since"][item] == "2026-09-17 01:17:03"
    assert doc["fault_since"][item] == "2026-09-08 09:01:53"


def test_an_onset_only_ever_moves_earlier_while_an_item_stays_down(tmp_path):
    """systemd resets InactiveEnterTimestamp when a periodic unit re-runs and
    fails again, so next week's probe answers LATER for the same unbroken
    outage. The carried value wins, which makes this file the only home for an
    onset that outlives journald (two days) and syslog rotation (about one)."""
    item = "failed-unit:ktp-identity-reconcile.service"
    t1 = build(tmp_path, [item], {}, {}, "2026-09-17 01:17:03",
               {item: "2026-09-08 09:01:53"})
    t2 = build(tmp_path, [item], t1, {}, "2026-09-22 09:17:03",
               {item: "2026-09-22 09:00:55"})
    assert t2["fault_since"][item] == "2026-09-08 09:01:53"


def test_an_onset_can_never_read_later_than_the_detection_date(tmp_path):
    """A probe answering later than `since` would SHRINK the age, the one
    direction that hides a fault. Clamped, so this can only make items older."""
    item = "failed-unit:x.service"
    doc = build(tmp_path, [item], {}, {}, "2026-09-10 00:00:00",
                {item: "2026-09-19 00:00:00"})
    assert doc["fault_since"] == {}          # clamped to `since`, so not repeated


def test_an_onset_drops_when_the_item_clears(tmp_path):
    """A fault that clears and returns is a new fault, not the old one resumed."""
    item = "failed-unit:x.service"
    t1 = build(tmp_path, [item], {}, {}, "2026-09-09 00:00:00",
               {item: "2026-09-08 09:01:53"})
    t2 = build(tmp_path, [], t1, {}, "2026-09-10 00:00:00")
    assert t2["fault_since"] == {}
    t3 = build(tmp_path, [item], t2, {}, "2026-09-20 00:00:00")
    assert t3["fault_since"] == {}
    assert t3["since"][item] == "2026-09-20 00:00:00"


def test_a_state_file_written_before_this_change_still_builds(tmp_path):
    """The shape on disk right now. It upgrades in place on the next run."""
    prev = {"updated_at": "x", "down": ["a"], "since": {"a": "2026-09-01 00:00:00"}}
    doc = build(tmp_path, ["a"], prev, {}, "2026-09-02 00:00:00")
    assert doc["since"]["a"] == "2026-09-01 00:00:00"
    assert doc["fault_since"] == {}


# --- fault_since_probe: what it refuses to answer ----------------------------
# `date -d ""` prints TODAY at midnight and exits 0. An unset systemd property
# would therefore land as a fresh timestamp -- the one direction that hides a
# fault -- so the raw string is shape-checked before date ever sees it.

def probe(tmp_path, item, stamp="Tue 2026-09-15 09:00:55 EDT",
          load="loaded", active="failed"):
    """Run fault_since_probe with systemctl stubbed. A shell function shadows
    the real binary, so this never asks the host anything. Properties come back
    in systemd's own order, not the requested one -- hence the shuffle."""
    out = "ActiveState=%s\nInactiveEnterTimestamp=%s\nLoadState=%s\n" % (
        active, stamp, load)
    body = "%s\nsystemctl() { printf '%%s' %s; }\nfault_since_probe %s\n" % (
        source(), shlex.quote(out), shlex.quote(item))
    p = tmp_path / "probe.sh"
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, p.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_a_real_systemd_stamp_becomes_an_onset(tmp_path):
    assert probe(tmp_path, "failed-unit:ktp-identity-reconcile.service") == \
        "2026-09-15 09:00:55"


def test_an_unset_property_answers_nothing_rather_than_today(tmp_path):
    """systemd leaves InactiveEnterTimestamp empty for a unit that never went
    inactive. Silence is the only safe answer; today's date -- which is what
    `date -d ""` returns, exiting 0 -- would read as a brand-new fault and take
    the item straight back under the gate it was meant to trip."""
    for raw in ("", "n/a", "0", "not-a-date", "Tue 2026-09-15", "2026-09-15 09:00:55"):
        assert probe(tmp_path, "failed-unit:x.service", stamp=raw) == "", repr(raw)


def test_a_unit_that_does_not_exist_is_not_a_fault_with_a_date(tmp_path):
    """`ActiveState`/`SubState` on a missing unit read inactive/dead, identical
    to a real stopped one. Only LoadState discriminates, so it is asked for."""
    assert probe(tmp_path, "failed-unit:typo.service", load="not-found") == ""


def test_a_running_unit_is_not_dated_from_the_last_time_it_stopped(tmp_path):
    """InactiveEnterTimestamp on an active unit is its last clean stop -- a
    healthy restart weeks ago, which would read as a weeks-old fault."""
    assert probe(tmp_path, "failed-unit:mysql.service", active="active") == ""


def test_only_failed_unit_items_are_probed(tmp_path):
    """No other item class has a durable onset signal on this box, and a guess
    dressed as a measurement is worse than an absent field."""
    for item in ("disk-growth:/", "hltv@27020=inactive", "capture-loss",
                 "mysql.service=failed"):
        assert probe(tmp_path, item) == "", item
