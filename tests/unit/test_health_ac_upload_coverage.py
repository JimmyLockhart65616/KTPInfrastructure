"""ktp-data-server-health.sh: can the aborted-upload detector still see anything?

`ac-upload-abort` reads one access log, because exactly one nginx server block
writes a format carrying `$upstream_response_time`. Two different things follow,
and the shipped check keeps them apart.

The gap is accepted and never alerts: every other vhost logs `combined` and runs
at the default `error` level, so an aborted transfer there is absent from the
error log and unclassifiable in the access log at the same time. It is printed
every run so it shrinks visibly when someone fixes it.

The regression does alert: if the upload vhost's format goes back to `combined`,
the scanner returns a clean 0 out of real traffic. The existing `unmeasurable`
leg only catches that while the window holds upload lines -- on a quiet night
`scanned` is 0 and the field could have been gone for days. So the baseline is
asserted against the config rather than inferred from traffic.

The fixture is the shape of the real effective config, with the vhost names and
paths that actually ship. No nginx is involved: the dump arrives on stdin.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

UPLOAD_LOG = "/var/log/nginx/api.ktpdod.com.access.log"

# The one format that can express an abort, verbatim from sites-available/api.ktpdod.com.
KTP_TIMED = """\
log_format ktp_timed '$remote_addr - $remote_user [$time_local] "$request" '
                     '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                     'rt=$request_time urt=$upstream_response_time rl=$request_length';
"""

# $uri drops the query string so a single-use OAuth code never lands on disk. It
# carries no timing fields, which is the whole point of listing it here.
KTP_ADMIN = """\
log_format ktp_admin_noquery '$remote_addr [$time_local] "$request_method $uri $server_protocol" '
                             '$status $body_bytes_sent "$http_user_agent"';
"""


def dump(upload_format="ktp_timed", extra_vhosts=(), declare=(KTP_TIMED, KTP_ADMIN)):
    """An `nginx -T`-shaped effective config: http{} default log, then server blocks."""
    parts = ["http {", "    access_log /var/log/nginx/access.log;", ""]
    parts += [t for t in declare]
    parts += [
        # the upload vhost: its own log, and the only format with urt
        "server {",
        "    server_name api.ktpdod.com;",
        "    access_log %s %s;" % (UPLOAD_LOG, upload_format),
        "    location /api/ { proxy_pass http://127.0.0.1:8088; }",
        "}",
        # the :80 twin of the same vhost -- own server block, inherits the shared log
        "server {",
        "    listen 80;",
        "    server_name api.ktpdod.com;",
        "    location / { return 301 https://$host$request_uri; }",
        "}",
        # a vhost with its own log but the built-in format
        "server {",
        "    server_name ac.ktpdod.com;",
        "    access_log /var/log/nginx/ac.ktpdod.com.access.log;",
        "}",
        # a vhost whose only access_log sits inside a location{}
        "server {",
        "    server_name ac-admin.ktpdod.com;",
        "    access_log /var/log/nginx/admin.ktpdod.com.access.log;",
        "    location /oauth/ {",
        "        access_log /var/log/nginx/admin.ktpdod.com.access.log ktp_admin_noquery;",
        "    }",
        "}",
        # a vhost with no access_log at all: inherits the http{} default
        "server {",
        "    server_name bundles.ktpdod.com;",
        "    location /api/ { proxy_pass http://127.0.0.1:8088; }",
        "}",
    ]
    parts += list(extra_vhosts)
    parts.append("}")
    return "\n".join(parts) + "\n"


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def coverage(tmp_path, config, *expected):
    """Run the shipped function over a fixture dump; return its rows as a dict."""
    cfg = tmp_path / "nginx-T.dump"
    cfg.write_text(config, encoding="utf-8", newline="\n")
    body = "%s\nac_upload_urt_coverage %s %s\n" % (
        block("ktp-ac-upload-coverage"),
        cfg.as_posix(),
        " ".join(expected or (UPLOAD_LOG,)))
    p = tmp_path / "probe.sh"
    p.write_text(body, encoding="utf-8", newline="\n")
    env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*", TZ="UTC")
    r = subprocess.run([BASH, p.as_posix()], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = {}
    for line in r.stdout.splitlines():
        k, v = line.split("\t", 1)
        out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


def test_one_block_is_covered_and_the_rest_are_named(tmp_path):
    """The shape that ships: a single urt-capable block, and the gap said out loud."""
    got = coverage(tmp_path, dump())
    assert got["blocks"] == 5
    assert got["covered"] == 1
    assert got["uncovered"] == 4
    assert got["formats_urt"] == "ktp_timed"
    # The gap is reported, not alerted: `lost` is what the caller turns into a
    # down item, and an accepted gap must never latch one.
    assert got["lost"] == ""
    # Naming them is the deliverable -- "some vhost" is not actionable.
    assert "ac.ktpdod.com" in got["uncovered_names"]
    assert "bundles.ktpdod.com" in got["uncovered_names"]


def test_the_upload_vhosts_own_port_80_block_is_not_covered(tmp_path):
    """Coverage is per server BLOCK, not per server_name.

    api.ktpdod.com appears twice: the :443 block carries ktp_timed and the :80
    redirect block inherits the shared log. Counting by name would report the
    vhost covered and hide the half that is not.
    """
    got = coverage(tmp_path, dump())
    assert got["uncovered_names"].count("api.ktpdod.com") == 1
    assert "api.ktpdod.com->access.log" in got["uncovered_names"]


def test_two_blocks_sharing_a_label_are_not_silently_collapsed(tmp_path):
    """A name list shorter than the count beside it reads as a lost block.

    The :443 and :80 halves of one vhost produce the same label whenever both
    inherit the shared log, and on the real config seventeen labels stand for
    twenty-one blocks.
    """
    twin = [
        "server { listen 443; server_name hud.ktpdod.com; }",
        "server { listen 80; server_name hud.ktpdod.com; }",
    ]
    got = coverage(tmp_path, dump(extra_vhosts=twin))
    assert got["uncovered"] == 6
    assert "hud.ktpdod.com->access.log x2" in got["uncovered_names"]


def test_dropping_the_format_is_a_regression_not_a_quiet_zero(tmp_path):
    """The failure this exists for: the detector keeps running and stops seeing.

    Nothing else notices. The scanner reports 0 aborts, `unmeasurable` stays
    silent on any night with no uploads in the window, and the log file is still
    there and still growing.
    """
    got = coverage(tmp_path, dump(upload_format=""))
    assert got["covered"] == 0
    assert UPLOAD_LOG in got["lost"]
    assert "now combined" in got["lost"]


def test_a_detector_pointed_at_a_log_nothing_writes_is_also_lost(tmp_path):
    """Same clean zero, different cause -- a renamed vhost or a typo'd baseline."""
    got = coverage(tmp_path, dump(), "/var/log/nginx/api.ktpdod.com.access.log.RENAMED")
    assert "no server block writes it" in got["lost"]
    # and the real log is still covered, so this is not a blanket failure
    assert got["covered"] == 1


def test_the_format_declaration_is_visible_across_vhost_files(tmp_path):
    """ktp_timed is declared inside the api vhost's own file and used from it.

    That works because sites-enabled is included inside http{}, but it couples
    the two: a second vhost adopting the format depends on the first still being
    enabled. The check reads formats from the whole dump for the same reason.
    """
    second = [
        "server {",
        "    server_name hud.ktpdod.com;",
        "    access_log /var/log/nginx/hud.ktpdod.com.access.log ktp_timed;",
        "}",
    ]
    got = coverage(tmp_path, dump(extra_vhosts=second))
    assert got["covered"] == 2
    assert "hud.ktpdod.com" not in got["uncovered_names"]


def test_a_format_that_does_not_exist_is_never_urt_capable(tmp_path):
    """Negative control. An unresolvable format name must read as no coverage.

    Without this the check could pass by resolving every unknown name to True and
    report full coverage over a config it had failed to parse.
    """
    got = coverage(tmp_path, dump(upload_format="ktp_timed_ZZZNOPE"))
    assert got["covered"] == 0
    assert UPLOAD_LOG in got["lost"]


def test_the_builtin_combined_format_is_recognised_without_being_declared(tmp_path):
    """`combined` is nginx's built-in and appears in no config file.

    A parser that only knows declared formats resolves it to unknown -- which
    happens to give the right verdict here and the wrong one for any check that
    later asks what a log DOES carry.
    """
    got = coverage(tmp_path, dump(declare=(KTP_TIMED,)))
    assert got["covered"] == 1
    assert got["uncovered"] == 4
