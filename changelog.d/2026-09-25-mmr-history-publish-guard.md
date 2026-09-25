### `mmr`: the weekly publish refuses to drop a week of accuracy history (2026-09-25)

The accuracy history only ever grows, and nothing enforced that. The restore step cannot tell a
**transient** clone failure from "`mmr-ratings` does not exist yet" — both leave the run holding
no prior payload, and it exits 0 on purpose so the first run is not a failure. So one network
blip on a Monday would have had the job rebuild the document with only that week in it and push
it over the season's earlier weeks, reporting success.

The publish step already clones the data branch, so the published copy is in hand there. It now
compares the two before overwriting and fails the job, with an annotation, if any week would be
lost. Compared as **sets**, not lengths: losing week 1 while gaining week 3 keeps the count and
is still a loss.

`methodology.py` gained a `__main__` for it, so the workflow calls the same tested code rather
than an inline copy — `test_the_guard_runs_as_the_workflow_invokes_it` drives it as a subprocess
exactly as the YAML does. Both previous failures in this feature passed their unit tests and
broke at the seam between a caller and what it called, so the seam is what is tested.

Rehearsed against the real branch: with the restore failed, a run publishing `[3]` over the
published `[1, 2]` is blocked and told to re-run; with the restore working, `[1, 2, 3]` goes
through.
