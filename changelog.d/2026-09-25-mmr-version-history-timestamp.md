### `mmr`: the accuracy history parses the timestamp the weekly job actually writes (2026-09-25)

`version_history` was empty on every real run. `weekly_summary.json` carries a **display**
timestamp — `run_weekly` writes `strftime("%Y-%m-%d %H:%M UTC")`, e.g. `2026-09-21 18:57 UTC` —
and the week was derived with `datetime.fromisoformat`, which cannot read it. Every row was
therefore dropped, so the document published an empty table with the job green.

The tests did not catch it because they used invented ISO-8601 timestamps. They now use strings
copied verbatim from the `weekly_summary.json` artifacts of runs 35045720142, 35641684672 and
35729323529, and `test_the_production_timestamp_format_parses` pins that shape directly.

`as_date` accepts both the display format and ISO, rather than `now` being reformatted: that
string is also the heading of `weekly_digest.md`, so changing it would have moved a human-facing
line to fix a parser.

Verified by replaying the three archived summaries through `build()` in order: weeks accumulate
`[1] → [1,2]`, the week-2 re-run replaces its row, and the result is the season's real trend —
week 1 at 9 matches and log-loss 0.6931, which is `ln(2)`, a literal coin flip, and week 2 at 16
matches and 0.6908. That first number is the damping working as designed on thin evidence, and
it is the reason the table carries log-loss next to accuracy.
