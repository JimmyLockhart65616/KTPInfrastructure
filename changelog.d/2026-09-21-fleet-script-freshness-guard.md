### `scripts`: a fleet writer that is behind `origin/main` now refuses instead of succeeding (2026-09-21)

A local checkout falls behind and nothing says so. Someone runs `stage-wave.py` out of it.
The old copy parses its arguments, opens 24 SSH sessions, stages the artifacts, verifies the
md5s and prints a clean 24/24 — and every gate it has never heard of simply does not run.
No flag was rejected, because a copy that lacks a flag never sees one; an unknown flag is a
usage error, a flag that was never passed is silence.

The measurable loss on the checkout this was found in, re-derived rather than quoted:
`scripts/stage-wave.py` there is missing `--pull-live`, `--base` and `--row-version`, the
unreconciled-previous-wave gate, and the wave-ledger write. `--pull-live` is the one that
costs something. It downloads each artifact's live counterpart before staging, and the fleet
keeps no rollback copies — the swap is `mv -f`, and none of these artifacts is
byte-reproducible, so the running build is the only copy of itself that exists. The ledger is
the same shape of loss one level up: the wave lands, no entry is written, and
`ktp-wave-ledger.py reconcile` is blind to it from then on. That already happened once and
was caught by hand on the 1.23.2 wave.

The standing remedy was a sentence in a doc — run it out of `git show origin/main:` instead —
which is a rule applied from memory, and therefore a rule applied sometimes.

- New `scripts/ktp_script_freshness.py`. `require_current(__file__, also=[...])` compares the
  file that is actually executing, and the siblings it loads, against `origin/main`. It asks
  `git diff` rather than recomputing a hash: these checkouts set `core.autocrlf=input` and
  carry a `.gitattributes`, so raw bytes and the stored blob legitimately differ and a
  hand-rolled comparison reports drift on files that are identical.
- The refusal names the loss, not the fact: which long options and which top-level functions
  the current version has and this one does not, which commits touched the path since,
  and — separately, because it is worse — whether the running copy matches no commit of that
  path at all rather than being a known older one.
- It is wired into the entry points, not offered as a check to remember: a check nobody
  invokes is the same defect one layer up, and a wrapper is another file that can go stale.
  Placed after `parse_args`, so `--help` still answers offline and a `--dry-run` does not
  (a dry run from a stale copy prints a plan that is wrong in the way that is hardest to see).
- Every answer that is not "identical to the ref" refuses: drift, no checkout, the path absent
  from the ref, a failed git call, and a fetch that failed on a copy that otherwise looks
  clean. Freshness of the ref is settled by fetching at run time; the accepted dependency is
  reaching the git remote while staging, which is strictly weaker than the 24 SSH sessions the
  operation already needs. A hash recorded in the tree was the alternative and it goes stale
  in the same file it is recorded in, where a stale copy carries a stale expectation that
  agrees with itself.
- Inert under pytest and GitHub Actions, and says so rather than staying quiet. In CI the
  provenance is the checked-out sha; in a test the harness is not a deploy, and the suite has
  to be able to run `main()` on a branch that is by definition not `origin/main` yet.
- `tests/unit/test_fleet_script_freshness.py` runs the guard against real git repos in a
  tmpdir, and locks the coverage: every `scripts/*.py` importing paramiko is either guarded or
  carries a written reason it cannot be. A new one that is neither fails the suite, and a
  reason whose script no longer exists fails too.

⚠️ **Not applied to the cron scripts, on purpose.** `audit-fleet-drift.py` and
`precache_audit.py` run out of `/opt/ktp-infra`, a checkout that is deliberately never
auto-pulled. Failing closed there would convert a stale-data problem into a no-data one, and
an audit that does not run is this same defect a level up.

⚠️ **`ktp-wave-ledger.py sweep` runs from `ktp-wave-sweep.timer` on the data server, also out
of `/opt/ktp-infra`.** That unit already states the requirement in a comment — *"Must be a
checkout of main: an older ledger script has no `sweep` and exits 2"* — so the guard enforces
something that was already true, and turns a cryptic exit 2 into a named report that its
`OnFailure=` alerts on. Nothing reaches that box until someone pulls it, and a pull makes it
current.

This guards against accident, not evasion. Anything here is bypassable by someone who wants
to; the failure it exists for is forgetting that a checkout got old, which nothing else on
this estate reports.
