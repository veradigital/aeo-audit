import unittest

from aeo_audit.audit import bots_blocked, snippet_block_reasons
from aeo_audit.audit import SEARCH_BOTS, TRAINING_BOTS
from aeo_audit.http import leak_hits
from aeo_audit.schema import ORG_TYPES, all_types, parse_nodes, validator_urls

class LeakTests(unittest.TestCase):
    def test_production_host_is_clean(self):
        self.assertEqual(leak_hits("https://www.example.com/product/"), [])

    def test_pantheon_is_a_leak(self):
        hits = leak_hits("https://live-example.pantheonsite.io/#organization")
        self.assertIn("pantheonsite.io", hits)


class SchemaParseTests(unittest.TestCase):
    def test_graph_types(self):
        html = """
        <script type="application/ld+json">{
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "WebPage", "@id": "https://example.com/"},
            {"@type": "Organization", "@id": "https://example.com/#org"}
          ]
        }</script>
        """
        nodes, fail = parse_nodes(html)
        self.assertFalse(fail)
        self.assertIn("Organization", all_types(nodes))

    def test_validator_urls(self):
        schema, rich = validator_urls("https://www.example.com/")
        self.assertIn("validator.schema.org", schema)
        self.assertIn("test/rich-results", rich)


class SnippetTests(unittest.TestCase):
    def test_clean_page_is_eligible(self):
        self.assertEqual(snippet_block_reasons({}, "<meta name=\"robots\" content=\"index, follow\">"), [])

    def test_nosnippet_blocks(self):
        html = '<meta name="robots" content="index, nosnippet">'
        self.assertTrue(snippet_block_reasons({}, html))

    def test_max_snippet_zero_blocks(self):
        html = "<meta name='googlebot' content='max-snippet: 0'>"
        reasons = snippet_block_reasons({}, html)
        self.assertEqual(len(reasons), 1)
        self.assertIn("max-snippet: 0", reasons[0])

    def test_x_robots_tag_blocks(self):
        reasons = snippet_block_reasons({"x-robots-tag": "nosnippet"}, "")
        self.assertIn("X-Robots-Tag", reasons[0])

    def test_noindex_blocks(self):
        html = '<meta name="robots" content="noindex, follow">'
        reasons = snippet_block_reasons({}, html)
        self.assertTrue(reasons)
        self.assertIn("noindex", reasons[0])

    def test_none_blocks(self):
        html = '<meta name="googlebot" content="none">'
        self.assertTrue(snippet_block_reasons({}, html))


class RobotsTests(unittest.TestCase):
    def test_star_allow_is_enough(self):
        text = "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n"
        self.assertEqual(bots_blocked(text, SEARCH_BOTS), [])
        self.assertEqual(bots_blocked(text, TRAINING_BOTS), [])

    def test_grouped_agents_share_a_block(self):
        text = "User-agent: OAI-SearchBot\nUser-agent: ChatGPT-User\nDisallow: /\n"
        blocked = bots_blocked(text, SEARCH_BOTS)
        self.assertIn("OAI-SearchBot", blocked)
        self.assertIn("ChatGPT-User", blocked)

    def test_training_block_does_not_block_search(self):
        text = "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\nUser-agent: Google-Extended\nDisallow: /\n"
        self.assertEqual(bots_blocked(text, SEARCH_BOTS), [])
        self.assertIn("GPTBot", bots_blocked(text, TRAINING_BOTS))

    def test_star_disallow_blocks_search(self):
        text = "User-agent: *\nDisallow: /\n"
        self.assertIn("PerplexityBot", bots_blocked(text, SEARCH_BOTS))

    def test_specific_allow_overrides_star(self):
        text = "User-agent: *\nDisallow: /\n\nUser-agent: PerplexityBot\nAllow: /\n"
        blocked = bots_blocked(text, SEARCH_BOTS)
        self.assertNotIn("PerplexityBot", blocked)
        self.assertIn("OAI-SearchBot", blocked)


class OrgTypeTests(unittest.TestCase):
    def test_local_subtypes_count(self):
        self.assertIn("HairSalon", ORG_TYPES)
        self.assertIn("LiquorStore", ORG_TYPES)
        self.assertIn("Organization", ORG_TYPES)


# ---- New module unit tests ----

class CrawlTests(unittest.TestCase):
    def test_normalize(self):
        from aeo_audit.crawl import _normalize
        self.assertEqual(
            _normalize("https://example.com/page/"),
            "https://example.com/page",
        )
        self.assertEqual(
            _normalize("https://example.com"),
            "https://example.com/",
        )

    def test_same_origin(self):
        from aeo_audit.crawl import _same_origin
        self.assertTrue(_same_origin("https://www.example.com/p", "https://example.com"))
        self.assertFalse(_same_origin("https://other.com/p", "https://example.com"))

    def test_extract_images(self):
        from aeo_audit.crawl import _extract_images
        html = '<img src="a.jpg" alt="pic"> <img src="b.jpg"> <img src="c.jpg" alt="">'
        total, missing = _extract_images(html)
        self.assertEqual(total, 3)
        self.assertEqual(missing, 2)

    def test_word_count(self):
        from aeo_audit.crawl import _word_count
        html = "<p>Hello world this is a test</p><script>var x=1;</script>"
        self.assertEqual(_word_count(html), 6)


class KeyphraseTests(unittest.TestCase):
    def test_density(self):
        from aeo_audit.keyphrase import _density
        text = "example widget is a great example widget tool"
        d = _density(text, "example widget")
        self.assertGreater(d, 0.3)

    def test_keyphrase_for_page(self):
        from aeo_audit.keyphrase import keyphrase_for_page
        from aeo_audit.config import Site, PageKeyphrase
        site = Site(slug="test", url="https://test.com", page_keyphrases=[
            PageKeyphrase(path="/about", keyphrase="about us test"),
        ])
        self.assertEqual(keyphrase_for_page(site, "/about"), "about us test")
        self.assertEqual(keyphrase_for_page(site, "/other", "gsc query"), "gsc query")
        self.assertEqual(keyphrase_for_page(site, "/other"), "")


class ContentCheckTests(unittest.TestCase):
    def test_page_type(self):
        from aeo_audit.content_check import _page_type
        self.assertEqual(_page_type("https://example.com/"), "homepage")
        self.assertEqual(_page_type("https://example.com/blog/post-1"), "blog")
        self.assertEqual(_page_type("https://example.com/about-us"), "about")
        self.assertEqual(_page_type("https://example.com/services/plumbing"), "service")

    def test_faq_schema_questions(self):
        from aeo_audit.content_check import _faq_schema_questions
        html = '''<script type="application/ld+json">{
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": "What is X?"},
                {"@type": "Question", "name": "How does Y work?"}
            ]
        }</script>'''
        qs = _faq_schema_questions(html)
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[0], "What is X?")

    def test_find_outdated(self):
        from aeo_audit.content_check import _find_outdated
        result = _find_outdated("Founded in 2019, updated 2024")
        self.assertIn("2019", result)


class ConsistencyTests(unittest.TestCase):
    def test_normalize_phone(self):
        from aeo_audit.consistency import _normalize_phone
        self.assertEqual(_normalize_phone("(312) 555-1234"), "3125551234")
        self.assertEqual(_normalize_phone("+1-312-555-1234"), "+13125551234")


class RecommendTests(unittest.TestCase):
    def test_orders_high_easy_before_high_hard(self):
        from aeo_audit.config import Site
        from aeo_audit.http import Check
        from aeo_audit.recommend import build_recommendations, homepage_title

        site = Site(
            slug="example",
            url="https://www.example.com",
            name="Example Co",
            product="Example Widget",
            vertical="warehouse software",
            money_action="https://www.example.com/contact/",
            meta_rules=__import__("aeo_audit.config", fromlist=["MetaRules"]).MetaRules(
                brand_suffix="Example Co"
            ),
        )
        audit = [
            Check("title", "fail", "Homepage title names the offer", "old services list"),
            Check("meta", "fail", "Meta description matches the offer", "167 chars"),
            Check("llms-quality", "fail", "llms.txt is a useful brief", "pantheonsite.io"),
        ]
        schema = [
            Check("schema-org-nap", "warn", "Organization contact fields", "Missing: telephone, email, address"),
        ]
        ai = [{"prompt": "Best warehouse software", "mentioned": False, "error": ""}]
        recs = build_recommendations(site, audit, schema, {
            "text": "Compatibility: desktop and cloud. up to 80% less training time.",
            "phone": "(312) 555-0100",
            "email": "hello@example.com",
            "address": "1 Main Street, Springfield, IL 62701",
            "claims": "up to 80% less training time",
        }, metas=[], ai_results=ai, psi_results=[])
        self.assertEqual(recs[0].impact, "high")
        self.assertEqual(recs[0].difficulty, "easy")
        self.assertIn("Warehouse Software", homepage_title(site))
        self.assertLessEqual(len(recs[0].draft), 60)
        kinds = [r.kind for r in recs]
        self.assertIn("schema", kinds)
        self.assertIn("content", kinds)
        hard = [r for r in recs if r.difficulty == "hard"]
        self.assertTrue(hard)
        self.assertGreater(recs.index(hard[0]), 0)
        nap = next(r for r in recs if r.kind == "schema" and "telephone" in r.draft)
        self.assertIn("(312) 555-0100", nap.draft)
        self.assertNotIn("pantheonsite.io", next(r.draft for r in recs if "llms.txt" in r.target))
        desc = next(r.draft for r in recs if r.kind == "description")
        self.assertNotIn("time Contact", desc)
        self.assertNotIn("NAP:", nap.draft)

    def test_legal_descriptions_do_not_pitch_the_product(self):
        from aeo_audit.config import MetaRules, Site
        from aeo_audit.recommend import _meta_recs

        site = Site(
            slug="example",
            url="https://www.example.com",
            name="Example Consulting Group",
            product="Example Widget",
            vertical="warehouse software",
            meta_rules=MetaRules(brand_suffix="Example Consulting Group"),
        )
        metas = [
            {
                "path": "/privacy-policy",
                "title": "Privacy Policy | Example",
                "checks": [{"rule": "meta-missing", "status": "fail"}],
            },
            {
                "path": "/terms-of-service",
                "title": "Terms of Service | Example",
                "checks": [{"rule": "meta-missing", "status": "fail"}],
            },
        ]
        recs = _meta_recs(site, metas)
        self.assertEqual(len(recs), 2)
        for rec in recs:
            self.assertNotIn("helps with", rec.draft)
            self.assertGreaterEqual(len(rec.draft), 120)
            self.assertLessEqual(len(rec.draft), 156)
        privacy = next(rec for rec in recs if "privacy-policy" in rec.target)
        terms = next(rec for rec in recs if "terms-of-service" in rec.target)
        self.assertIn("privacy policy", privacy.draft.lower())
        self.assertIn("terms of service", terms.draft.lower())


class CrawlFilterTests(unittest.TestCase):
    def test_skip_xml_urls(self):
        from aeo_audit.crawl import _is_page_url
        self.assertFalse(_is_page_url("https://example.com/sitemap.xml"))
        self.assertFalse(_is_page_url("https://example.com/page-sitemap.xml"))

    def test_skip_pdf_urls(self):
        from aeo_audit.crawl import _is_page_url
        self.assertFalse(_is_page_url("https://example.com/doc.pdf"))

    def test_skip_image_urls(self):
        from aeo_audit.crawl import _is_page_url
        self.assertFalse(_is_page_url("https://example.com/photo.jpg"))
        self.assertFalse(_is_page_url("https://example.com/logo.png"))

    def test_allow_html_pages(self):
        from aeo_audit.crawl import _is_page_url
        self.assertTrue(_is_page_url("https://example.com/"))
        self.assertTrue(_is_page_url("https://example.com/about/"))
        self.assertTrue(_is_page_url("https://example.com/contact-us/"))

    def test_skip_wp_admin(self):
        from aeo_audit.crawl import _is_page_url
        self.assertFalse(_is_page_url("https://example.com/wp-admin/post.php"))
        self.assertFalse(_is_page_url("https://example.com/wp-json/wp/v2/posts"))

    def test_meta_skip_non_html(self):
        from aeo_audit.meta import _is_page_url
        self.assertFalse(_is_page_url("https://example.com/doc.pdf"))
        self.assertTrue(_is_page_url("https://example.com/about/"))

