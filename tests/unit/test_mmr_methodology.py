"""The rating_methodology payload: the transparency document the website shows.

Its numbers must be the numbers the ratings actually use, so the tests pin
them to the source modules rather than to literals.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mmr"))

PARAMS = {
    "method_version": "momentum_ledger_v1", "generated_at": "2026-09-19T00:00:00+00:00",
    "definitions": {"fallback": {"curves": "pooled", "scoring": {"cap": 1.0, "capout": 1.0}}},
    "corpus": {"halves": 174, "multikills": 1757},
    "rho": {"value": 0.324},
    "pooled": {"cap": {"A": 1.83, "lam": 0.106, "n_multikills": 1757, "half_life_s": 6.5}},
    "maps": {
        "dod_thunder2": {"halves": 72, "official_halves": 16, "multikills": 723, "caps": 887, "capouts": 21,
                         "curves": {"cap": {"A": 10.0, "lam": 0.25, "n_multikills": 723, "half_life_s": 2.8}},
                         "scoring": {"coef": {"cap": 2.8, "hold3": 0.06, "hold4": 0.33, "capout": 18.3},
                                     "r2": 0.887, "n_team_halves": 32}},
        "dod_armory_b6": {"halves": 2, "official_halves": 0, "multikills": 9, "caps": 20, "capouts": 0,
                          "curves": None, "scoring": None},
    },
}


def build(**kwargs):
    import methodology as X
    return X.build(PARAMS, generated_at="2026-09-19T12:00:00+00:00", **kwargs)


class Contract(unittest.TestCase):
    def test_kind_and_sections(self):
        p = build()
        self.assertEqual(p["kind"], "rating_methodology")
        for section in ("ktpr_v2", "mmr", "momentum"):
            self.assertIn("what", p[section])
        self.assertTrue(p["provisional"])

    def test_a_fitted_map_carries_its_values_sample_and_fit_quality(self):
        m = build()["momentum"]["maps"]["dod_thunder2"]
        self.assertEqual(m["sample"]["official_halves"], 16)
        self.assertEqual(m["momentum_curves"]["cap"]["half_life_s"], 2.8)
        self.assertEqual(m["scoring"]["r2"], 0.887)
        self.assertEqual(m["scoring"]["n_team_halves"], 32)

    def test_a_thin_map_says_what_it_falls_back_to(self):
        m = build()["momentum"]["maps"]["dod_armory_b6"]
        self.assertEqual(m["momentum_curves"], {"uses": "pooled"})
        self.assertEqual(m["scoring"]["uses"], "fallback")
        self.assertEqual(m["scoring"]["fallback"], {"cap": 1.0, "capout": 1.0})

    def test_version_history_is_empty_rather_than_absent_before_any_run(self):
        self.assertEqual(build()["version_history"], [])

    def test_carries_the_columns_the_aggregate_insert_needs(self):
        p = build()
        self.assertIsInstance(p["source_report_count"], int)
        self.assertIsInstance(p["report_schema_version"], int)


# Copied verbatim from the week-2 run's own weekly_summary.json artifact
# (run 35641684672). run_weekly writes strftime("%Y-%m-%d %H:%M UTC"), NOT
# ISO 8601 -- the first cut of this feature parsed only ISO and so emitted an
# empty history against every real summary while invented-ISO tests passed.
WK2 = {"generated_at": "2026-09-21 18:57 UTC", "completed_matches": 16,
       "accuracy": 0.562, "log_loss": 0.6908, "upsets": 0,
       "headline": "16 matches rated, 56% accuracy"}


class VersionHistory(unittest.TestCase):
    """How the ratings have improved as data landed -- drew's transparency call
    2026-09-23: a reader should see the trend, not just today's numbers."""

    def setUp(self):
        import methodology as X
        self.X = X

    def test_a_weeks_row_carries_its_accuracy_sample_and_date(self):
        row = self.X.week_entry(WK2)
        self.assertEqual(row["week"], 2)
        self.assertEqual(row["date"], "2026-09-21")
        self.assertEqual(row["accuracy_pct"], 56.2)
        self.assertEqual(row["completed_matches"], 16)
        self.assertEqual(row["upsets_pct"], 0.0)
        self.assertEqual(row["log_loss"], 0.6908)

    def test_the_production_timestamp_format_parses(self):
        """run_weekly writes a DISPLAY timestamp, not ISO 8601.

        These three strings are copied from the weekly_summary.json artifacts of
        runs 35045720142, 35641684672 and 35729323529. Parsing only ISO here is
        what made the first cut of this feature publish an empty history on every
        real run with a green job, so the real shape is pinned, not assumed.
        """
        self.assertEqual(self.X.week_of("2026-09-16 01:51 UTC"), 1)
        self.assertEqual(self.X.week_of("2026-09-21 18:57 UTC"), 2)
        self.assertEqual(self.X.week_of("2026-09-22 12:47 UTC"), 2)
        self.assertEqual(self.X.as_date("2026-09-21 18:57 UTC").isoformat(), "2026-09-21")

    def test_the_week_comes_from_the_runs_own_timestamp(self):
        # Season starts 2026-09-13, so the 13th is week 1 and the 20th week 2.
        # ISO stays accepted -- report_service and any future producer may use it.
        self.assertEqual(self.X.week_of("2026-09-13T00:00:00+00:00"), 1)
        self.assertEqual(self.X.week_of("2026-09-19T23:59:00+00:00"), 1)
        self.assertEqual(self.X.week_of("2026-09-20T00:00:00+00:00"), 2)
        self.assertEqual(self.X.week_of("2026-09-28T14:00:00+00:00"), 3)
        self.assertEqual(self.X.week_of("2026-09-13"), 1)

    def test_a_week_with_nothing_rated_is_not_a_zero_percent_row(self):
        # The pre-season run writes a summary with no matches; a 0% row there
        # would read as the ratings having got worse.
        self.assertIsNone(self.X.week_entry(
            {"generated_at": "2026-09-14T14:00:00+00:00", "completed_matches": 0,
             "headline": "No completed matches yet"}))

    def test_an_unreadable_summary_drops_its_row_rather_than_failing_the_run(self):
        self.assertIsNone(self.X.week_entry({"completed_matches": 16}))
        self.assertIsNone(self.X.week_entry(None))
        self.assertIsNone(self.X.week_of("not a date"))

    def test_weeks_accumulate_oldest_first(self):
        p = build(summary=WK2, prior_history=[{"week": 1, "date": "2026-09-14",
                                              "accuracy_pct": 44.4, "completed_matches": 9}])
        self.assertEqual([r["week"] for r in p["version_history"]], [1, 2])
        self.assertEqual(p["version_history"][0]["accuracy_pct"], 44.4)
        self.assertEqual(p["version_history"][1]["accuracy_pct"], 56.2)

    def test_a_rerun_of_a_week_replaces_that_row_instead_of_appending_a_second(self):
        # Every value is refit on the whole corpus each run, so the newer row is
        # the truth about that week; two rows for week 2 would read as progress.
        stale = {"week": 2, "date": "2026-09-21", "accuracy_pct": 50.0, "completed_matches": 14}
        p = build(summary=WK2, prior_history=[stale])
        self.assertEqual([r["week"] for r in p["version_history"]], [2])
        self.assertEqual(p["version_history"][0]["accuracy_pct"], 56.2)

    def test_prior_history_comes_from_the_last_published_payload(self):
        import json as J
        import tempfile
        from pathlib import Path as P
        d = P(tempfile.mkdtemp())
        (d / "payload.json").write_text(J.dumps(
            {"kind": "rating_methodology", "version_history": [{"week": 1, "accuracy_pct": 44.4}]}),
            encoding="utf-8")
        self.assertEqual(self.X.load_prior_history(d / "payload.json"),
                         [{"week": 1, "accuracy_pct": 44.4}])

    def test_a_missing_or_corrupt_prior_payload_starts_the_history_over_quietly(self):
        import tempfile
        from pathlib import Path as P
        d = P(tempfile.mkdtemp())
        self.assertEqual(self.X.load_prior_history(d / "absent.json"), [])
        (d / "junk.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.X.load_prior_history(d / "junk.json"), [])

    def test_history_carries_no_player_rows_either(self):
        body = json.dumps(build(summary=WK2))
        for k in ("players", "player_id", "steam_id", "alias"):
            self.assertNotIn(f'"{k}"', body)


class PinnedToSource(unittest.TestCase):
    """If someone changes a weight in the code, this document follows."""

    def test_ktpr_weights_are_the_config_defaults(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from ktpr_v2 import KtprV2Config
        cfg = KtprV2Config()
        w = {c["name"]: c["weight"] for c in build()["ktpr_v2"]["components"]}
        self.assertEqual(w, {"swing": cfg.swing_weight, "kast_f": cfg.kast_weight,
                             "output": cfg.output_weight, "multikill": cfg.multikill_weight})

    def test_mmr_values_are_the_ladders(self):
        import ladder
        import mmr_payload as MMRP
        import performance as PF
        m = build()["mmr"]
        self.assertEqual(m["prediction"]["k"], ladder.EVIDENCE_K)
        self.assertEqual(m["min_matches"], MMRP.MIN_MATCHES_FOR_DISPLAY)
        self.assertEqual(m["performance_weighting"]["strength"], PF.DEFAULT_STRENGTH)
        self.assertFalse(m["performance_weighting"]["enabled"])

    def test_display_scale_matches_the_dto(self):
        d = build()["ktpr_v2"]["display"]
        self.assertEqual((d["floor"], d["center"], d["scale"]), (50, 100, 15))
        self.assertIn("max(50, 100 + 15", d["equation"])


class Privacy(unittest.TestCase):
    def test_no_player_shaped_keys_anywhere(self):
        body = json.dumps(build())
        for k in ("players", "player_id", "steam_id", "alias"):
            self.assertNotIn(f'"{k}"', body)


class ImportGuards(unittest.TestCase):
    def setUp(self):
        import methodology as X
        self.X = X
        self.good = build()

    def test_a_well_formed_payload_passes(self):
        self.assertEqual(self.X.validate_for_import(self.good), [])

    def test_the_wrong_kind_is_refused(self):
        self.assertTrue(self.X.validate_for_import({**self.good, "kind": "mmr_openskill"}))

    def test_a_missing_section_is_refused(self):
        bad = dict(self.good); del bad["mmr"]
        self.assertIn("missing section 'mmr'", " ".join(self.X.validate_for_import(bad)))

    def test_player_rows_are_refused_even_here(self):
        bad = {**self.good, "players": [{"name": "x"}]}
        self.assertIn("about nobody", " ".join(self.X.validate_for_import(bad)))

    def test_a_non_object_is_refused_rather_than_crashing(self):
        self.assertTrue(self.X.validate_for_import(None))


if __name__ == "__main__":
    unittest.main()
