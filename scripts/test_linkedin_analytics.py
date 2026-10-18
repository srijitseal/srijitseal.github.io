"""Check import semantics and public LinkedIn snapshots without network access."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest

from import_linkedin_analytics import chart_scale, combine_snapshots, import_metrics, number, post_url, reaction_indices


ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.linkedin.com/posts/srijitseal_test-share-123-example"


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.period = {"start": "2026-01-31", "end": "2026-02-01"}
        self.data = {
            "years": {"2026": {"period": self.period, "totals": {"reactions": 5}, "reactions_observed_at": "2026-02-01"}},
            "posts": [{"id": "test", "url": URL, "published_at": "2026-01-31", "reactions": 3, "reactions_observed_at": "2026-02-01"}],
        }
        self.sheets = {
            "DISCOVERY": [("Overall Performance", "1/31/2026 - 2/1/2026"), ("Impressions", "30"), ("Members reached", "20")],
            "ENGAGEMENT": [("Date", "Impressions", "Engagements"), ("1/31/2026", "10", "9"), ("2/1/2026", "20", "9")],
            "FOLLOWERS": [("Total followers on 2/1/2026", "100")],
            "TOP POSTS": [("50 posts",), (), ("Post URL", "Post Publish Date", "Engagements", "", "Post URL", "Post Publish Date", "Impressions"),
                          (URL, "1/31/2026", "999", "", URL, "1/31/2026", "28")],
        }

    def run_import(self, **kwargs):
        return import_metrics(self.data, self.sheets, "2026-02-02", **kwargs)

    def test_imports_impressions_not_engagements(self):
        result = self.run_import()
        self.assertEqual(result["posts"][0]["impressions"], 28)
        self.assertEqual(result["posts"][0]["reactions"], 3)
        self.assertEqual(result["years"]["2026"]["totals"]["reactions"], 5)
        self.assertEqual(result["posts"][0]["reactions_observed_at"], "2026-02-01")

    def test_months_are_sorted_and_partial(self):
        result = self.run_import()
        self.assertEqual(result["years"]["2026"]["monthly_impressions"], [
            {"month": "2026-01", "impressions": 10, "partial": True},
            {"month": "2026-02", "impressions": 20, "partial": True},
        ])

    def test_never_carries_reactions_into_a_different_period(self):
        self.data["years"]["2026"]["period"] = {"start": "2026-01-01", "end": "2026-02-01"}
        result = self.run_import()
        self.assertIsNone(result["years"]["2026"]["totals"]["reactions"])
        self.assertIsNone(result["years"]["2026"]["reactions_observed_at"])

    def test_explicitly_verified_reactions(self):
        result = self.run_import(reactions=7)
        self.assertEqual(result["years"]["2026"]["totals"]["reactions"], 7)
        self.assertEqual(result["years"]["2026"]["reactions_observed_at"], "2026-02-02")

    def test_missing_post_is_unknown_not_zero(self):
        self.sheets["TOP POSTS"] = self.sheets["TOP POSTS"][:3]
        result = self.run_import()
        self.assertIsNone(result["posts"][0]["impressions"])
        self.assertEqual(result["posts"][0]["reactions"], 3)

    def test_zero_is_known(self):
        self.sheets["TOP POSTS"][3] = (None, None, None, "", URL, "1/31/2026", "0")
        result = self.run_import()
        self.assertEqual(result["posts"][0]["impressions"], 0)
        self.assertFalse(result["posts"][0]["impressions_is_partial"])

    def test_no_guessed_publication_dates(self):
        del self.data["posts"][0]["published_at"]
        with self.assertRaisesRegex(ValueError, "No publication date"):
            self.run_import()

    def test_no_changed_publication_dates(self):
        self.data["posts"][0]["published_at"] = "2026-01-30"
        with self.assertRaisesRegex(ValueError, "Publication date changed"):
            self.run_import()

    def test_mismatched_total_rejected(self):
        self.sheets["DISCOVERY"][1] = ("Impressions", "31")
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.run_import()

    def test_missing_day_rejected(self):
        self.sheets["ENGAGEMENT"].pop()
        with self.assertRaisesRegex(ValueError, "every day"):
            self.run_import()

    def test_duplicate_day_rejected(self):
        self.sheets["ENGAGEMENT"].append(self.sheets["ENGAGEMENT"][1])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.run_import()

    def test_export_does_not_change_input(self):
        before = deepcopy(self.data)
        self.run_import()
        self.assertEqual(self.data, before)

    def test_rejects_unknown_headers(self):
        self.sheets["TOP POSTS"][2] = ("Post URL", "Date", "Reactions", "", "Post URL", "Date", "Views")
        with self.assertRaisesRegex(ValueError, "headers"):
            self.run_import()

    def test_rejects_future_period(self):
        with self.assertRaisesRegex(ValueError, "observation date"):
            import_metrics(self.data, self.sheets, "2026-01-30")

    def test_rejects_multiple_years(self):
        self.sheets["DISCOVERY"][0] = ("Overall Performance", "12/31/2025 - 2/1/2026")
        with self.assertRaisesRegex(ValueError, "one calendar year"):
            self.run_import()

    def test_rejects_invalid_counts(self):
        for value in (-1, 1.5, None, True, "unknown"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)

    def test_rejects_foreign_urls(self):
        for url in ("javascript:alert(1)", "https://example.com/posts/srijitseal_a", "https://www.linkedin.com/posts/another-person"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                post_url(url)

    def add_prior_snapshot(self):
        prior = deepcopy(self.run_import()["years"]["2026"])
        prior["period"] = {"start": "2025-01-31", "end": "2025-02-01"}
        prior["totals"]["followers"] = 80
        prior["monthly_impressions"] = [
            {"month": "2025-01", "impressions": 10, "partial": True},
            {"month": "2025-02", "impressions": 20, "partial": True},
        ]
        self.data["years"]["2025"] = prior
        return prior

    def test_preserves_other_year_and_does_not_sum_audience(self):
        prior = self.add_prior_snapshot()
        result = self.run_import()
        self.assertEqual(result["years"]["2025"], prior)
        self.assertEqual(result["combined"]["totals"]["impressions"], 60)
        self.assertEqual(result["combined"]["totals"]["followers"], 100)
        self.assertIsNone(result["combined"]["totals"]["members_reached"])

    def test_reimport_does_not_double_count(self):
        self.data = self.run_import()
        result = self.run_import()
        self.assertEqual(result["combined"]["totals"]["impressions"], 30)
        self.assertEqual(result["posts"][0]["impressions"], 28)

    def test_missing_older_period_marks_post_count_as_lower_bound(self):
        self.add_prior_snapshot()
        self.data["posts"][0]["published_at"] = "2024-01-01"
        self.sheets["TOP POSTS"][3] = (None, None, None, "", URL, "1/1/2024", "28")
        result = self.run_import()
        self.assertEqual(result["posts"][0]["impressions"], 28)
        self.assertTrue(result["posts"][0]["impressions_is_partial"])

    def test_post_not_yet_published_does_not_need_older_count(self):
        self.add_prior_snapshot()
        result = self.run_import()
        self.assertFalse(result["posts"][0]["impressions_is_partial"])

    def test_rejects_overlap(self):
        result = self.run_import()
        result["years"]["duplicate"] = deepcopy(result["years"]["2026"])
        with self.assertRaisesRegex(ValueError, "overlapping"):
            combine_snapshots(result)


class IndexAndChartTests(unittest.TestCase):
    def test_standard_h_index_example(self):
        result = reaction_indices([{"reactions": n} for n in (3, 0, 6, 1, 5)])
        self.assertEqual(result, {"posts": 5, "reactions": 15, "h_index": 3, "i10_index": 0})

    def test_i10_includes_exactly_ten(self):
        result = reaction_indices([{"reactions": n} for n in (0, 9, 10, 11, 50)])
        self.assertEqual(result["i10_index"], 3)

    def test_empty_indices(self):
        self.assertEqual(reaction_indices([]), {"posts": 0, "reactions": 0, "h_index": 0, "i10_index": 0})

    def test_h_index_is_bounded_by_post_count(self):
        self.assertEqual(reaction_indices([{"reactions": 1000}] * 4)["h_index"], 4)

    def test_scale_uses_rounded_ticks_and_zero_baseline(self):
        scale = chart_scale([{"impressions": 391377}])
        self.assertEqual(scale["maximum"], 400000)
        self.assertEqual([tick["value"] for tick in scale["ticks"]], [400000, 300000, 200000, 100000, 0])
        self.assertEqual([tick["position"] for tick in scale["ticks"]], [100, 75, 50, 25, 0])

    def test_scale_never_clips_data_or_divides_by_zero(self):
        for count in (0, 1, 9, 100, 271633, 2641890):
            scale = chart_scale([{"impressions": count}])
            self.assertGreater(scale["maximum"], 0)
            self.assertGreaterEqual(scale["maximum"], count)
            self.assertEqual(scale["ticks"][-1]["value"], 0)


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "_data/linkedin.json").read_text())

    def test_months_reconcile_with_period_impressions(self):
        for snapshot in [*self.data["years"].values(), self.data["combined"]]:
            if not snapshot.get("period"):
                continue
            months = snapshot["monthly_impressions"]
            self.assertEqual(sum(m["impressions"] for m in months), snapshot["totals"]["impressions"])
            self.assertEqual([m["month"] for m in months], sorted({m["month"] for m in months}))

    def test_unique_posts_with_observation_dates(self):
        posts = self.data["posts"]
        self.assertEqual(len(posts), len({p["id"] for p in posts}))
        self.assertEqual(len(posts), len({p["url"] for p in posts}))
        for post in posts:
            post_url(post["url"])
            for key in ("published_at", "reactions_observed_at", "impressions_observed_at"):
                if post.get(key):
                    self.assertLessEqual(date.fromisoformat(post[key]), date.fromisoformat(self.data["snapshot_date"]))
            self.assertGreaterEqual(post["reactions"], 0)
            self.assertTrue(post["title"] and post["summary"] and post["topic"])

    def test_combined_snapshot_is_reproducible(self):
        regenerated = deepcopy(self.data)
        combine_snapshots(regenerated)
        self.assertEqual(regenerated, self.data)

    def test_archive_covers_at_least_three_years(self):
        self.assertTrue({"2024", "2025", "2026"} <= {p["published_at"][:4] for p in self.data["posts"]})
        self.assertEqual(self.data["default_year"], "all")

    def test_only_requested_public_data(self):
        self.assertEqual(set(self.data), {"schema_version", "snapshot_date", "profile_url", "default_year", "years", "combined", "posts", "post_indices"})
        for post in self.data["posts"]:
            self.assertEqual(set(post), {"id", "title", "summary", "topic", "url", "published_at", "reactions", "reactions_observed_at",
                                        "impressions", "impressions_observed_at", "impressions_period", "impressions_is_partial", "impression_snapshots"})

    def test_indices_use_archived_reactions_not_period_totals(self):
        self.assertEqual(self.data["post_indices"]["all"], reaction_indices(self.data["posts"]))
        self.assertLessEqual(self.data["post_indices"]["all"]["h_index"], len(self.data["posts"]))
        self.assertLessEqual(self.data["post_indices"]["all"]["i10_index"], len(self.data["posts"]))
        self.assertNotEqual(self.data["post_indices"]["all"]["reactions"], self.data["combined"]["totals"]["reactions"])


if __name__ == "__main__":
    unittest.main()
