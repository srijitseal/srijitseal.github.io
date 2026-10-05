"""Offline regression tests for citation baselines and weekly refreshes."""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import update_live_stats as stats


def metric(count, source="OpenAlex", date="2026-10-12"):
    return {
        "citations": count,
        "source": source,
        "source_url": "https://example.org/" + source.replace(" ", ""),
        "updated_at": date,
    }


class CitationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.scholar = metric(190, "Google Scholar", "2026-10-05")

    def test_lower_or_equal_openalex_keeps_scholar_and_its_date(self):
        for count in (0, 114, 190):
            with self.subTest(count=count):
                selected = stats.select_citation_metric(self.scholar, metric(count))
                self.assertEqual(selected, {**self.scholar, "display": "190"})

    def test_strictly_higher_openalex_replaces_source_and_date(self):
        selected = stats.select_citation_metric(self.scholar, metric(191))
        self.assertEqual(selected, {**metric(191), "display": "191"})

    def test_later_drop_or_failure_preserves_previous_high_and_date(self):
        previous = stats.select_citation_metric(self.scholar, metric(200))
        for fresh in (metric(199), metric(150), metric(None), {}):
            with self.subTest(fresh=fresh):
                selected = stats.select_citation_metric(self.scholar, previous, fresh)
                self.assertEqual(selected, previous)

    def test_equal_openalex_does_not_change_previous_observation_date(self):
        previous = metric(200)
        selected = stats.select_citation_metric(self.scholar, previous, metric(200, date="2026-10-19"))
        self.assertEqual(selected["updated_at"], "2026-10-12")

    def test_new_higher_scholar_baseline_can_take_over(self):
        selected = stats.select_citation_metric(metric(220, "Google Scholar"), metric(200), metric(210))
        self.assertEqual(selected["citations"], 220)
        self.assertEqual(selected["source"], "Google Scholar")

    def test_unavailable_is_not_zero(self):
        self.assertEqual(stats.select_citation_metric(metric(None), {}), {})
        self.assertEqual(stats.select_citation_metric(metric(None), metric(0))["citations"], 0)

    def test_invalid_counts_cannot_poison_saved_high(self):
        for invalid in (-1, True, False, 1.5, "1.5", "", "1,02", "NaN"):
            with self.subTest(invalid=invalid):
                self.assertEqual(stats.citation_value(invalid), None)
                selected = stats.select_citation_metric(self.scholar, metric(invalid))
                self.assertEqual(selected["citations"], 190)
        self.assertEqual(stats.citation_value("1,027"), 1027)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        paths = {
            "LIVE_STATS_FILE": root / "live_stats.yml",
            "PUBLICATION_METRICS_FILE": root / "publication_metrics.yml",
            "SCHOLAR_BASELINE_FILE": root / "scholar_baseline.json",
        }
        patcher = patch.multiple(stats, **paths)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pubs = [{"id": "paper", "title": "Test paper"}, {"id": "blank", "title": "No count"}]
        patcher = patch.object(stats, "publications", return_value=self.pubs)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(stats.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.baseline = {
            "checked_at": "2026-10-05",
            "source_url": "https://scholar.google.com/citations?user=example",
            "citations": 1027,
            "publications": {
                "paper": {"citations": 190, "scholar_id": "example:paper"},
                "blank": {"citations": None},
            },
        }
        stats.SCHOLAR_BASELINE_FILE.write_text(json.dumps(self.baseline))
        self.date = datetime(2026, 10, 12)

    def test_baseline_validation_rejects_unknown_paper_and_bad_count(self):
        self.assertEqual(stats.scholar_baseline(), self.baseline)
        for records in ({"typo": {"citations": 1}}, {"paper": {"citations": -1}}):
            self.baseline["publications"] = records
            stats.SCHOLAR_BASELINE_FILE.write_text(json.dumps(self.baseline))
            with self.assertRaises(ValueError):
                stats.scholar_baseline()

    def test_per_paper_source_link(self):
        self.assertIn("citation_for_view=example:paper", stats.scholar_metric(self.baseline, "paper")["source_url"])

    def test_first_refresh_seeds_scholar_even_if_api_fails(self):
        with patch.object(stats, "openalex_work_for_publication", side_effect=urllib.error.URLError("offline")):
            with contextlib.redirect_stderr(io.StringIO()):
                metrics = stats.publication_metrics(self.baseline, "2026-10-12")
        self.assertEqual(metrics["paper"]["citations"], 190)
        self.assertEqual(metrics["paper"]["updated_at"], "2026-10-05")
        self.assertNotIn("blank", metrics)

    def test_old_metrics_get_original_meta_date_not_today(self):
        stats.write_publication_metrics({"paper": {"citations": 200, "source": "OpenAlex", "openalex_id": "https://openalex.org/W1"}}, datetime(2026, 10, 4))
        with patch.object(stats, "openalex_work_for_publication", return_value=None):
            with contextlib.redirect_stderr(io.StringIO()):
                metrics = stats.publication_metrics(self.baseline, "2026-10-12")
        self.assertEqual(metrics["paper"]["updated_at"], "2026-10-04")
        self.assertEqual(metrics["paper"]["source_url"], "https://openalex.org/W1")

    def test_saved_paper_metrics_do_not_read_adjacent_records(self):
        stats.write_publication_metrics({"paper": metric(190, "Google Scholar"), "blank": metric(1)}, self.date)
        self.assertEqual(stats.previous_publication_metric("paper")["citations"], "190")
        self.assertEqual(stats.previous_publication_metric("blank")["citations"], "1")
        self.assertNotIn("citations", stats.previous_publication_metric("_meta"))

    def test_weekly_write_read_cycle_never_lowers_counts(self):
        for count, expected, source, date in (
            (114, 190, "Google Scholar", "2026-10-05"),
            (190, 190, "Google Scholar", "2026-10-05"),
            (200, 200, "OpenAlex", "2026-10-12"),
            (195, 200, "OpenAlex", "2026-10-12"),
            (None, 200, "OpenAlex", "2026-10-12"),
        ):
            with self.subTest(count=count):
                work = {"id": "https://openalex.org/W1", "cited_by_count": count}
                with patch.object(stats, "openalex_work_for_publication", return_value=work):
                    with contextlib.redirect_stderr(io.StringIO()):
                        metrics = stats.publication_metrics(self.baseline, "2026-10-12")
                stats.write_publication_metrics(metrics, self.date)
                saved = stats.previous_publication_metric("paper")
                self.assertEqual(int(saved["citations"]), expected)
                self.assertEqual(saved["source"], source)
                self.assertEqual(saved["updated_at"], date)
                self.assertEqual(saved["openalex_id"], "https://openalex.org/W1")

    def test_author_total_uses_same_floor_independent_of_papers(self):
        for count, expected, source, date in (
            (856, 1027, "Google Scholar", "2026-10-05"),
            (1027, 1027, "Google Scholar", "2026-10-05"),
            (1100, 1100, "OpenAlex", "2026-10-12"),
            (1050, 1100, "OpenAlex", "2026-10-12"),
            (None, 1100, "OpenAlex", "2026-10-12"),
        ):
            with self.subTest(count=count):
                with patch.object(stats, "openalex_author", return_value={"cited_by_count": count, "id": "https://openalex.org/A1"}):
                    with contextlib.redirect_stderr(io.StringIO()):
                        selected = stats.total_citation_metric(self.baseline, "2026-10-12")
                stats.write_stats({"citations": {**selected, "value": selected["citations"]}}, self.date)
                saved = stats.previous_citation_metric()
                self.assertEqual(saved["citations"], expected)
                self.assertEqual(saved["source"], source)
                self.assertEqual(saved["updated_at"], date)

    def test_main_updates_files_with_api_failures_and_preserves_stars(self):
        stats.write_stats({"github_stars": {"value": 151, "display": "151"}}, self.date)
        with patch.object(stats, "count_publications", return_value=2), \
             patch.object(stats, "config_value", return_value="example"), \
             patch.object(stats, "openalex_author", side_effect=urllib.error.URLError("offline")), \
             patch.object(stats, "openalex_work_for_publication", side_effect=urllib.error.URLError("offline")), \
             patch.object(stats, "github_stars", side_effect=urllib.error.URLError("offline")), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(stats.main(), 0)
        self.assertEqual(stats.previous_int("citations"), 1027)
        self.assertEqual(stats.previous_int("github_stars"), 151)
        self.assertEqual(stats.previous_int("publications"), 2)
        self.assertEqual(stats.previous_publication_metric("paper")["citations"], "190")


if __name__ == "__main__":
    unittest.main()
