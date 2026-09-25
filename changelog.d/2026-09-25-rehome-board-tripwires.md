### `docs`: the merge button breaks a fast-forward guard permanently (2026-09-25)

Recorded in CONTRIBUTING.md under *Branches and pull requests*. No GitHub merge method
fast-forwards, so reconciling a branch guarded by `git merge-base --is-ancestor` through the
UI puts a commit on it that the upstream will never contain. The guard then fails for good,
and because it warns and exits 0 rather than failing the run, it goes on reporting success.

The reconciler this was learned on is gone with `preprod`, and the rule is written about the
guard shape rather than that branch — KTPAMXX, KTPMatchHandler and KTPHLStatsX still keep a
`preprod`. `docs/handover/PREPROD_BRANCHING.md`, which holds the rest of the reconciler's
history, points at the rule instead of repeating it.

### `docs`: the two ways an MMR import goes wrong are now in the runbook (2026-09-25)

`docs/runbooks/REPORT_PIPELINE_INSTALL.md` gains the `import-mmr` step, which the page
described the install for but never the use of.

- **Run it from the serving checkout, as the service account.** `import-mmr` imports its
  validators from `--repo`, so a behind or personal checkout guards a production write with
  code the box is not running, and the `auth_socket` grant is tied to the account name.
- **Never substitute `ratings_current.json`.** It is the ladder's internal state keyed by raw
  numeric player ids, and the aggregate it would be imported as is published publicly.
  `validate_for_import` refuses it on shape, not on the identifiers, so the leak is stopped by
  accident — which is not a property to rely on.
