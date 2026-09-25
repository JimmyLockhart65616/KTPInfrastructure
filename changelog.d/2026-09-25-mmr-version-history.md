### `mmr`: the methodology document now shows how the ratings have improved, week by week (2026-09-25)

`rating_methodology` gains `version_history`: one row per season week, oldest first, carrying
the week, date, matches rated, accuracy, log-loss and upsets. The website renders it as a table
under Stats, so the league can see the model converging and argue with it rather than only
seeing today's numbers.

`log_loss` rides along with accuracy deliberately. Predictions are damped toward a coin flip
until there is evidence, so a low early accuracy is the model admitting it does not know yet;
accuracy alone would read as the model being wrong.

Two properties worth knowing when reading the table:

- **A week with nothing rated produces no row**, rather than a 0% one, which would read as a
  regression.
- **Re-rating a week replaces its row rather than appending a second.** Every value is refit on
  the whole corpus each run, so the table is what the current model says about each week, not a
  frozen record of what it said at the time.

The history's only durable home is the `mmr-ratings` branch. A weekly job has no memory between
runs, so the workflow restores the previously published payload before the run and the document
is built after that run's summary exists. Built the other way round — reading a summary file
from its own fresh checkout — the history is empty on every run and the job still goes green.
