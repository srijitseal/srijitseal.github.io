"""Original-post classification and safe merging, using synthetic public pages."""

from copy import deepcopy
from contextlib import redirect_stdout
import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from import_linkedin_posts import main, merge_originals, parse_public_post, post_copy, source_url
from import_linkedin_analytics import combine_snapshots, reaction_indices


ID = "7529036941124820992"
SOURCE = "https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A" + ID
CANONICAL = "https://www.linkedin.com/posts/srijitseal_example-activity-7529036942089363456-test"


def page(**overrides):
    post = {"@type": "SocialMediaPosting", "@id": CANONICAL, "datePublished": "2026-11-19T04:24:49Z",
            "author": {"url": "https://www.linkedin.com/in/srijitseal"}, "headline": "An original post",
            "articleBody": "An original post\n\nMore detail about the research.",
            "interactionStatistic": [{"interactionType": "https://schema.org/LikeAction", "userInteractionCount": 12}]}
    post.update(overrides)
    return '<script type="application/ld+json">' + json.dumps(post) + '</script><article class="main-feed-activity-card" data-attributed-urn="urn:li:share:' + ID + '"></article>'


class PublicPostTests(unittest.TestCase):
    def test_original_is_verified_from_public_author_and_identity(self):
        result = parse_public_post(page(), SOURCE)
        self.assertEqual(result["status"], "original")
        self.assertEqual(result["reactions"], 12)
        self.assertEqual(result["published_at"], "2026-11-19")

    def test_repost_with_commentary_is_excluded(self):
        result = parse_public_post(page(sharedContent={"author": {"name": "Another author"}}), SOURCE)
        self.assertEqual(result["status"], "excluded")

    def test_self_reshare_is_also_excluded(self):
        result = parse_public_post(page(sharedContent={"author": {"name": "Srijit Seal"}}), SOURCE)
        self.assertEqual(result["status"], "excluded")

    def test_dom_reshare_marker_is_enough(self):
        html = page().replace('</article>', '<div data-test-id="feed-reshare-content"></div></article>')
        self.assertEqual(parse_public_post(html, SOURCE)["status"], "excluded")

    def test_other_author_is_excluded(self):
        self.assertEqual(parse_public_post(page(author={"url": "https://www.linkedin.com/in/somebody-else"}), SOURCE)["status"], "excluded")

    def test_authwall_is_not_public_evidence(self):
        self.assertEqual(parse_public_post('<h1>Sign in</h1>', SOURCE)["status"], "unverified")

    def test_recommendation_or_redirect_cannot_match_another_post(self):
        self.assertEqual(parse_public_post(page(), SOURCE.replace(ID, "1234567890123456789"))["status"], "unverified")

    def test_related_posts_do_not_replace_main_post_or_make_it_a_reshare(self):
        related = '<article class="main-feed-activity-card related-posts__crosslink" data-attributed-urn="urn:li:share:1234567890123456789"><div data-test-id="feed-reshare-content"></div></article>'
        self.assertEqual(parse_public_post(page() + related, SOURCE)["status"], "original")

    def test_missing_reaction_count_is_not_zero(self):
        self.assertIsNone(parse_public_post(page(interactionStatistic=[]), SOURCE)["reactions"])

    def test_zero_reaction_count_is_preserved(self):
        statistics = [{"interactionType": "https://schema.org/LikeAction", "userInteractionCount": 0}]
        self.assertEqual(parse_public_post(page(interactionStatistic=statistics), SOURCE)["reactions"], 0)

    def test_no_comment_counts_substituted_for_likes(self):
        statistics = [{"interactionType": "https://schema.org/CommentAction", "userInteractionCount": 50}]
        self.assertIsNone(parse_public_post(page(interactionStatistic=statistics), SOURCE)["reactions"])

    def test_no_authored_text_is_excluded(self):
        self.assertEqual(parse_public_post(page(articleBody=""), SOURCE)["status"], "excluded")

    def test_public_excerpt_keeps_original_words(self):
        title, summary = post_copy(parse_public_post(page(), SOURCE))
        self.assertEqual(title, "An original post")
        self.assertEqual(summary, "More detail about the research.")

    def test_single_sentence_does_not_repeat_in_summary(self):
        title, summary = post_copy({"headline": "One sentence.", "text": "One sentence."})
        self.assertEqual((title, summary), ("One sentence.", ""))

    def test_heading_in_same_paragraph_is_not_repeated(self):
        title, summary = post_copy({"headline": "First sentence.", "text": "First sentence. More detail."})
        self.assertEqual((title, summary), ("First sentence.", "More detail."))

    def test_heading_whitespace_is_normalized(self):
        title, summary = post_copy({"headline": "First  sentence.", "text": "First sentence.\nMore detail."})
        self.assertEqual((title, summary), ("First sentence.", "More detail."))

    def test_source_url_rejects_unrelated_or_credential_urls(self):
        for url in ("https://example.com/", "https://www.linkedin.com/messages/", "https://user:pass@www.linkedin.com/posts/srijitseal_a", SOURCE + "?token=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                source_url(url)
        self.assertEqual(source_url(SOURCE), SOURCE)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.data = {"snapshot_date": "2026-10-18", "years": {}, "posts": []}
        self.record = dict(parse_public_post(page(), SOURCE), source_url=SOURCE, observed_at="2026-11-21")

    def test_import_is_idempotent(self):
        once, _ = merge_originals(self.data, [self.record], "2026-11-21")
        twice, _ = merge_originals(once, [self.record], "2026-11-21")
        self.assertEqual(once, twice)
        self.assertEqual(len(twice["posts"]), 1)

    def test_unknowns_and_reposts_never_create_posts(self):
        records = [{"source_url": SOURCE, "status": status} for status in ("unverified", "excluded")]
        result, _ = merge_originals(self.data, records, "2026-11-21")
        self.assertFalse(result["posts"])

    def test_existing_titles_and_verified_reaction_counts_survive(self):
        self.data, _ = merge_originals(self.data, [self.record], "2026-11-21")
        self.data["posts"][0].update(title="Curated title", reactions=20)
        before = deepcopy(self.data)
        result, _ = merge_originals(self.data, [self.record], "2026-11-21")
        self.assertEqual(result["posts"][0]["title"], "Curated title")
        self.assertEqual(result["posts"][0]["reactions"], 20)
        self.assertEqual(self.data, before)

    def test_confirmed_reshare_is_removed(self):
        self.data, _ = merge_originals(self.data, [self.record], "2026-11-21")
        record = dict(self.record, status="excluded", reason="Repost or reshare with commentary")
        result, changes = merge_originals(self.data, [record], "2026-11-21")
        self.assertFalse(result["posts"])
        self.assertEqual(changes["removed_reshares"], 1)

    def test_cached_reactions_keep_their_observation_date(self):
        result, _ = merge_originals(self.data, [self.record], "2026-11-22")
        self.assertEqual(result["posts"][0]["reactions_observed_at"], "2026-11-21")
        self.assertEqual(result["snapshot_date"], "2026-11-21")

    def test_missing_counts_do_not_inflate_indices_or_count_as_zero(self):
        self.assertEqual(reaction_indices([{"reactions": None}, {"reactions": 12}]),
                         {"posts": 1, "reactions": 12, "h_index": 1, "i10_index": 1})


class OfflineImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.shares = self.root / "Shares.csv"
        self.data = self.root / "linkedin.json"
        self.review = self.root / "review"
        self.review.mkdir()
        with self.shares.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Date", "ShareLink", "ShareCommentary", "SharedUrl", "MediaUrl", "Visibility"])
            writer.writerow(["2026-11-19 04:24:49", SOURCE, "Unverified export commentary", "", "", "MEMBER_NETWORK"])
        self.data.write_text(json.dumps({"snapshot_date": "2026-10-18", "years": {}, "posts": []}))
        self.record = dict(parse_public_post(page(headline="Public title " + chr(0x1F389)), SOURCE),
                           source_url=SOURCE, observed_at="2026-11-21", parser_version=2)
        self.cache = self.review / (hashlib.sha256(SOURCE.encode()).hexdigest() + ".json")

    def run_import(self, *flags):
        argv = ["import_linkedin_posts.py", str(self.shares), "--review-dir", str(self.review), "--data", str(self.data), *flags]
        with patch("sys.argv", argv), redirect_stdout(StringIO()), patch("socket.socket", side_effect=AssertionError("Network access forbidden")):
            main()

    def test_missing_evidence_never_publishes_export_commentary(self):
        self.run_import("--apply")
        result = json.loads(self.data.read_text())
        self.assertFalse(result["posts"])
        self.assertEqual(result["snapshot_date"], "2026-10-18")

    def test_dry_run_does_not_change_data(self):
        self.cache.write_text(json.dumps(self.record))
        before = self.data.read_bytes()
        self.run_import()
        self.assertEqual(self.data.read_bytes(), before)

    def test_offline_apply_uses_only_verified_text_and_literal_unicode(self):
        self.cache.write_text(json.dumps(self.record))
        self.run_import("--apply")
        content = self.data.read_text()
        self.assertNotIn("Unverified export commentary", content)
        self.assertIn(chr(0x1F389), content)
        self.assertEqual(len(json.loads(content)["posts"]), 1)

    def test_mismatched_cache_is_rejected_without_writing(self):
        self.record["source_url"] = CANONICAL
        self.cache.write_text(json.dumps(self.record))
        before = self.data.read_bytes()
        with self.assertRaisesRegex(ValueError, "source URL"):
            self.run_import("--apply")
        self.assertEqual(self.data.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
