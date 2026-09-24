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

    def test_version_history_builds_from_weekly_summary(self):
        import tempfile
        summary_data = {
            "generated_at": "2026-09-22T13:00:00+00:00",
            "completed_matches": 16,
            "accuracy": 0.562,
            "upsets": 0,
            "headline": "16 matches, 56.2% accuracy"
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            json.dump(summary_data, f)
            f.flush()
            p = build(summary_path=f.name)
        self.assertEqual(len(p["version_history"]), 1)
        entry = p["version_history"][0]
        self.assertEqual(entry["week"], 2)
        self.assertEqual(entry["date"], "2026-09-22")
        self.assertEqual(entry["accuracy_pct"], 56.2)
        self.assertEqual(entry["completed_matches"], 16)
        self.assertEqual(entry["upsets_pct"], 0.0)

    def test_carries_the_columns_the_aggregate_insert_needs(self):
        p = build()
        self.assertIsInstance(p["source_report_count"], int)
        self.assertIsInstance(p["report_schema_version"], int)


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
