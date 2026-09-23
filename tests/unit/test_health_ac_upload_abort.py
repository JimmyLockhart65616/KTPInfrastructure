"""ktp-data-server-health.sh: an AC evidence bundle that never arrived is a state.

Six session bundles were lost in the fortnight to 2026-09-22. Every one was an
aborted transfer -- the client stopped sending mid-body, nginx answered it
directly, and `urt=-` records that ktp-ac-api was never reached. Nothing AC-side
holds a trace, and nginx logs the cause at `info`, below the default `error`
level, so `api.ktpdod.com.error.log` has been 0 bytes since 2026-07-18. The class
was invisible by configuration rather than by absence.

The scanner is extracted from the shipped script by marker, so renaming or
deleting it fails this file rather than testing a copy that no longer ships. No
log server is involved: the fixtures are the real line shapes with documentation
addresses (RFC 5737) substituted for the client addresses.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

# 2026-09-20 in EDT. The burst that motivated this: four uploads aborted inside
# nine minutes of a match-end herd, while neighbouring uploads in the same second
# completed. Verbatim shapes from api.ktpdod.com.access.log.3.gz.
BURST = """\
192.0.2.11 - - [20/Sep/2026:15:50:58 -0400] "POST /api/session/upload HTTP/1.1" 200 108 "-" "-" rt=0.656 urt=0.131 rl=2294988
192.0.2.12 - - [20/Sep/2026:15:51:32 -0400] "POST /api/session/upload HTTP/1.1" 400 0 "-" "-" rt=1.008 urt=- rl=1589703
192.0.2.13 - - [20/Sep/2026:15:54:01 -0400] "POST /api/session/upload HTTP/1.1" 400 0 "-" "-" rt=1.219 urt=- rl=983493
192.0.2.14 - - [20/Sep/2026:15:59:14 -0400] "POST /api/session/upload HTTP/1.1" 408 0 "-" "-" rt=71.951 urt=- rl=1049029
192.0.2.15 - - [20/Sep/2026:15:59:50 -0400] "POST /api/session/upload HTTP/1.1" 400 0 "-" "-" rt=8.915 urt=- rl=7225799
192.0.2.16 - - [20/Sep/2026:16:00:04 -0400] "POST /api/session/upload HTTP/1.1" 200 110 "-" "-" rt=1.549 urt=0.228 rl=1670362
"""

# Each of these is a 400, or on the upload path, or both -- and none is a lost
# bundle. They are the reason the discriminator is urt and not the status.
NOT_LOSSES = """\
192.0.2.21 - - [20/Sep/2026:21:03:40 -0400] "POST /api/session/upload HTTP/1.1" 400 481 "-" "-" rt=0.050 urt=0.016 rl=34768
198.51.100.7 - - [20/Sep/2026:21:04:00 -0400] "GET / HTTP/1.1" 400 264 "-" "Mozilla/5.0 (compatible; Scanner/1.1)" rt=0.000 urt=- rl=164
198.51.100.8 - - [20/Sep/2026:21:04:01 -0400] "LEAKIX" 400 166 "-" "-" rt=0.124 urt=- rl=0
198.51.100.9 - - [20/Sep/2026:21:04:02 -0400] "" 400 0 "-" "-" rt=0.137 urt=- rl=0
192.0.2.22 - - [20/Sep/2026:21:04:03 -0400] "GET /api/session/uploadZZZNOPE HTTP/2.0" 404 0 "-" "curl/8.5.0" rt=0.000 urt=- rl=51
192.0.2.23 - - [20/Sep/2026:21:04:04 -0400] "POST /api/session/upload?retry=2 HTTP/1.1" 200 99 "-" "-" rt=1.785 urt=0.306 rl=1923103
"""

# The format before the 2026-09-16 log_format change. These lines cannot carry
# urt, so scoring them returns zero aborts out of real upload traffic.
OLD_FORMAT = """\
192.0.2.31 - - [13/Sep/2026:11:00:00 -0400] "POST /api/session/upload HTTP/1.1" 400 0 "-" "-"
192.0.2.32 - - [13/Sep/2026:11:00:01 -0400] "POST /api/session/upload HTTP/1.1" 200 108 "-" "-"
"""

# 2026-09-20 10:17 EDT, the start of the window the 16:17 cron run would read.
CUTOFF_1017 = 1789913820
# 2026-09-20 15:17 EDT, the 21:17 run's window start -- the burst is still in it.
CUTOFF_1517 = 1789931820
# 2026-09-20 16:17 EDT, the 22:17 run's window start -- the burst has aged out.
CUTOFF_1617 = 1789935420


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def bash(tmp_path, body, name="probe.sh"):
    # From a file, not `bash -c`: msys2 re-parses a multi-line -c argument on
    # Windows and the failure looks like a bug in the script under test.
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    # `/api/session/upload` reaches the scanner as `C:/Program Files/Git/api/...`
    # under Git Bash, because msys2 rewrites any argument shaped like a POSIX
    # path. Production is Linux and never does this, so unset it here rather than
    # working around it in the shipped script -- and the symptom, an argument
    # that silently does not match, reads as a broken detector.
    env = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
    r = subprocess.run([BASH, p.as_posix()], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def scan(tmp_path, cutoff, *logs, uri="/api/session/upload"):
    """Run the shipped scanner over fixture log files; return its rows as a dict."""
    paths = []
    for i, content in enumerate(logs):
        p = tmp_path / ("access%d.log" % i)
        p.write_text(content, encoding="utf-8", newline="\n")
        paths.append(p.as_posix())
    body = "%s\nac_upload_abort_scan %d %s %s\n" % (
        block("ktp-ac-upload-abort"), cutoff, uri, " ".join(paths))
    out = {}
    for line in bash(tmp_path, body).splitlines():
        k, v = line.split("\t", 1)
        out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


def test_the_september_burst_is_found_and_counted(tmp_path):
    """The nine minutes that cost four bundles, as the 16:17 run would read them."""
    got = scan(tmp_path, CUTOFF_1017, BURST)
    assert got["aborted"] == 4
    assert got["breakdown"] == "3x400, 1x408"
    assert got["bytes"] == 7225799
    assert got["first"] == "2026-09-20 15:51:32"
    assert got["last"] == "2026-09-20 15:59:50"
    # The two neighbours that completed in the same minutes are counted as
    # uploads and not as losses: a herd is not itself the failure.
    assert got["uploads"] == 6


def test_the_status_alone_is_not_the_detector(tmp_path):
    """Every line here is a 400, or on the upload path, or both. None is a loss.

    The 21:03:40 row is the sharp one: the API answered 400 in 16 ms to a 34 KB
    body, so that bundle arrived and was rejected -- already visible AC-side, and
    a different problem. Counting it would put routine rejections and internet
    scanners into a channel that must only ever carry lost evidence.
    """
    got = scan(tmp_path, CUTOFF_1017, NOT_LOSSES)
    assert got["aborted"] == 0
    assert "breakdown" not in got
    # Two of the six are genuine upload-path requests the API answered.
    assert got["uploads"] == 2
    assert got["fieldless"] == 0 and got["undated"] == 0


def test_a_rotated_pre_2026_09_16_file_reads_unmeasurable_not_clean(tmp_path):
    """The trap this check exists to avoid becoming.

    rt/urt/rl only exist from the 2026-09-16 log_format change onward. Measured
    against production: api.ktpdod.com.access.log.10.gz holds 21,766 lines and
    127 real session uploads, and scoring it for aborts returns 0 -- a clean bill
    of health from a file that structurally cannot produce a finding. Those lines
    must be counted as unreadable so the caller can say so.
    """
    got = scan(tmp_path, 0, OLD_FORMAT)
    assert got["aborted"] == 0
    assert got["fieldless"] == len(OLD_FORMAT.splitlines())
    # And not silently reclassified as traffic that was fine.
    assert got["uploads"] == 0


def test_the_format_boundary_inside_one_file_is_caught(tmp_path):
    """The real rotation looked like this: one file, both formats.

    api.ktpdod.com.access.log.7.gz carries 1182 lines of which 1152 have urt --
    the cutover landed mid-file. Aborts after the boundary are still scored; the
    lines before it are reported as unreadable rather than as quiet.
    """
    got = scan(tmp_path, 0, OLD_FORMAT + BURST)
    assert got["aborted"] == 4
    assert got["fieldless"] == 2


def test_lines_older_than_the_window_are_not_counted(tmp_path):
    assert scan(tmp_path, CUTOFF_1617, BURST)["aborted"] == 0
    assert scan(tmp_path, CUTOFF_1517, BURST)["aborted"] == 4


def test_a_line_whose_timestamp_will_not_parse_is_not_dropped(tmp_path):
    """It cannot be placed inside or outside the window, so it cannot be dismissed."""
    got = scan(tmp_path, CUTOFF_1017, "this is not an access log line\n\n" + BURST)
    assert got["undated"] == 1
    assert got["aborted"] == 4


def test_several_files_are_one_window(tmp_path):
    """Production reads today's log and yesterday's; a window spans both."""
    got = scan(tmp_path, CUTOFF_1017, BURST, NOT_LOSSES)
    assert got["aborted"] == 4
    assert got["uploads"] == 8


def test_a_missing_rotated_file_is_not_an_error(tmp_path):
    """`.log.1` does not exist on the day of install, and that is not a fault."""
    body = "%s\nac_upload_abort_scan 0 /api/session/upload %s\n" % (
        block("ktp-ac-upload-abort"), (tmp_path / "nope.log").as_posix())
    assert "aborted\t0" in bash(tmp_path, body)


def replay(tmp_path, series):
    """Run a per-run abort count through the real latch, carrying the
    previous-down set between runs the way the hourly cron does."""
    prev = tmp_path / "prev.list"
    prev.write_text("", encoding="utf-8")
    src = block("ktp-alert-latch")
    verdicts = []
    for i, count in enumerate(series):
        body = ("%s\nPREV_LIST=%s\nAC_UPLOAD_ABORT_WARN=1\nAC_UPLOAD_ABORT_CLEAR=1\n"
                "if latched ac-upload-abort %d \"$AC_UPLOAD_ABORT_WARN\" "
                "\"$AC_UPLOAD_ABORT_CLEAR\"; then echo YES; else echo NO; fi\n"
                % (src, prev.as_posix(), count))
        fired = bash(tmp_path, body, "probe%d.sh" % i).strip() == "YES"
        verdicts.append(fired)
        prev.write_text("ac-upload-abort\n" if fired else "", encoding="utf-8")
    return verdicts


def test_a_match_night_burst_is_one_alert_and_one_recovery(tmp_path):
    """Replayed from the real 2026-09-20 counts, hour by hour.

    The scanner over that day's log at each :17 cron run returns
    0, 4, 4, 4, 4, 4, 4, 1, 1, 0 -- four losses inside one window, then a fifth
    at 21:54 that arrives while the item is already down. `latched` is reported
    on the first run and on every run after it until the count reaches zero, so
    the transition report speaks exactly twice: once when it starts and once when
    it ends. Fifteen alerts across a match night would be muted, and a muted
    alert protects nothing.
    """
    verdicts = replay(tmp_path, [0, 4, 4, 4, 4, 4, 4, 1, 1, 0])
    assert verdicts == [False] + [True] * 8 + [False]
    # One rising edge and one falling edge is the whole conversation.
    edges = [i for i in range(1, len(verdicts)) if verdicts[i] != verdicts[i - 1]]
    assert len(edges) == 2


def test_one_lost_bundle_is_enough(tmp_path):
    """Six in a fortnight is the base rate; a floor above one would watch nothing."""
    assert replay(tmp_path, [1])[0] is True
