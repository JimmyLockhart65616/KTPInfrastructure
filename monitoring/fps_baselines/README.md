# Fleet FPS Baselines

Structured snapshots of fleet `[KTP_PROFILE] frames=N fps=X.Y` data, captured for before/after comparisons when fleet-wide changes land.

## Format

Each snapshot is a JSON file named `fleet_fps_<YYYY-MM-DD>_<label>.json` with:

```json
{
  "label": "pre-jit",
  "captured_at_utc": "2026-04-23T...",
  "description": "what was / wasn't true at capture time",
  "context": { ... relevant state flags ... },
  "fleet_stats":        { "n", "p50", "p99", "mean", "stdev", "min", "max",
                          "pct_in_nfo_window", "pct_within_10" },
  "per_host_stats":     { "<host>": { same fields } },
  "per_instance_stats": { "<host:port>": { same fields } }
}
```

## Methodology

Samples pulled via SSH+grep from each instance's `~/dod-<port>/log/console/` — the current live log plus any log rotated today. Pattern: `[KTP_PROFILE] frames=<N> fps=<X.Y>`. This fires every `ktp_profile_interval` seconds (default 10s), so each instance generates ~8640 samples/day.

Window: current + today-rotated log ≈ 12-48h depending on restart timing. Adjust the grep command if you need a specific window.

Pull script is inline in the conversation that produced each snapshot — no persistent script yet. If we find ourselves running it >3× it's worth extracting to `scripts/pull-fleet-fps.py`.

## Snapshots

| File | Label | Captured | Purpose |
|------|-------|----------|---------|
| `fleet_fps_2026-04-23_pre-jit.json` | pre-jit | 2026-04-23 (pre-3AM restart) | Baseline before the fleet-wide `debug` flag strip activates JIT on all KTP plugins. Compare against the post-JIT snapshot to isolate the interpreted→JIT delta without other variables moving. |

## Comparison quick-ref

When adding a new snapshot, compute deltas vs the most recent relevant baseline:

- **p50 shift** — did the median fps move?
- **stdev change** — tighter distribution (less jitter) or wider?
- **`pct_in_nfo_window` / `pct_within_10` shift** — changes to the tail of the distribution, separate from median
- **Per-instance outliers** — any instance whose delta is meaningfully different from its host's average? Flag for investigation.

For JIT A/B specifically: the most interesting instance is **ATL:27016** which pre-JIT had σ=30.74 (4× the next worst). If its σ normalizes post-JIT to ~8, that's evidence interpreted-plugin tail latency was the cause.
