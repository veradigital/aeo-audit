import json
import tempfile
import unittest
from pathlib import Path

from aeo_audit.config import MetaRules, Site
from aeo_audit.meta import (
    PageMeta,
    ProposedEntry,
    RuleResult,
    _extract_meta_description,
    _extract_og,
    _extract_canonical,
    _extract_robots_directives,
    _focus_phrase,
    _is_non_indexable,
    _keyword_stuff_score,
    _pixel_width_estimate,
    _extract_sitemap_urls,
    check_meta_rules,
    load_proposed,
)


def _site(**overrides) -> Site:
    defaults = dict(
        slug="test",
        url="https://www.example.com",
        name="Test Co",
        product="Test Product (TP)",
        meta_rules=MetaRules(
            product_required_pages=["/", "/product/"],
            brand_suffix="Test Co",
        ),
    )
    defaults.update(overrides)
    return Site(**defaults)


def _page(**overrides) -> PageMeta:
    defaults = dict(
        url="https://www.example.com/page/",
        path="/page/",
        title="Page Topic | Test Co",
        meta="This is a well-written meta description that explains the page topic clearly for searchers and AI engines.",
        h1s=["Page Topic Heading"],
        meta_tag_count=1,
        body_text="page topic heading and more content about the subject",
    )
    defaults.update(overrides)
    return PageMeta(**defaults)


class MetaExtractionTests(unittest.TestCase):
    def test_extract_meta_description(self):
        html = '<meta name="description" content="Hello world">'
        text, count = _extract_meta_description(html)
        self.assertEqual(text, "Hello world")
        self.assertEqual(count, 1)

    def test_extract_meta_description_reversed_attrs(self):
        html = '<meta content="Reversed order" name="description">'
        text, count = _extract_meta_description(html)
        self.assertEqual(text, "Reversed order")
        self.assertEqual(count, 1)

    def test_extract_meta_missing(self):
        html = "<html><head><title>No meta</title></head></html>"
        text, count = _extract_meta_description(html)
        self.assertIsNone(text)
        self.assertEqual(count, 0)

    def test_extract_duplicate_meta_tags(self):
        html = (
            '<meta name="description" content="First">'
            '<meta name="description" content="Second">'
        )
        text, count = _extract_meta_description(html)
        self.assertEqual(text, "First")
        self.assertEqual(count, 2)

    def test_extract_og_title(self):
        html = '<meta property="og:title" content="OG Title">'
        self.assertEqual(_extract_og(html, "title"), "OG Title")

    def test_extract_og_missing(self):
        self.assertEqual(_extract_og("<html></html>", "title"), "")

    def test_extract_canonical(self):
        html = '<link rel="canonical" href="https://www.example.com/page/">'
        self.assertEqual(_extract_canonical(html), "https://www.example.com/page/")

    def test_extract_robots_noindex(self):
        html = '<meta name="robots" content="noindex, nofollow">'
        dirs = _extract_robots_directives(html)
        self.assertIn("noindex", dirs)
        self.assertIn("nofollow", dirs)

    def test_extract_robots_clean(self):
        html = '<meta name="robots" content="index, follow">'
        dirs = _extract_robots_directives(html)
        self.assertIn("index", dirs)
        self.assertNotIn("noindex", dirs)


class SitemapTests(unittest.TestCase):
    def test_extract_sitemap_urls(self):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://www.example.com/</loc></url>
          <url><loc>https://www.example.com/about/</loc></url>
        </urlset>"""
        urls = _extract_sitemap_urls(xml)
        self.assertEqual(len(urls), 2)
        self.assertIn("https://www.example.com/", urls)


class NonIndexableTests(unittest.TestCase):
    def test_noindex_is_non_indexable(self):
        pm = _page(robots_directives=["noindex", "follow"])
        self.assertTrue(_is_non_indexable(pm))

    def test_none_directive_is_non_indexable(self):
        pm = _page(robots_directives=["none"])
        self.assertTrue(_is_non_indexable(pm))

    def test_redirect_is_non_indexable(self):
        pm = _page(is_redirect=True)
        self.assertTrue(_is_non_indexable(pm))

    def test_canonical_elsewhere(self):
        pm = _page(
            url="https://www.example.com/old/",
            path="/old/",
            canonical="https://www.example.com/new/",
        )
        self.assertTrue(_is_non_indexable(pm))

    def test_self_canonical_is_indexable(self):
        pm = _page(
            url="https://www.example.com/page/",
            path="/page/",
            canonical="https://www.example.com/page/",
        )
        self.assertFalse(_is_non_indexable(pm))

    def test_clean_page_is_indexable(self):
        pm = _page()
        self.assertFalse(_is_non_indexable(pm))


class FocusPhraseTests(unittest.TestCase):
    def test_pipe_separator(self):
        self.assertEqual(
            _focus_phrase("Warehouse Software | Example", {}, "/"),
            "Warehouse Software",
        )

    def test_dash_separator(self):
        self.assertEqual(
            _focus_phrase("Warehouse Software - Example", {}, "/"),
            "Warehouse Software",
        )

    def test_override(self):
        overrides = {"/custom/": "Custom Phrase"}
        self.assertEqual(
            _focus_phrase("Ignored Title | Brand", overrides, "/custom/"),
            "Custom Phrase",
        )

    def test_no_separator(self):
        self.assertEqual(_focus_phrase("Just a Title", {}, "/"), "Just a Title")


class PixelWidthTests(unittest.TestCase):
    def test_narrow_chars_shorter(self):
        narrow = _pixel_width_estimate("iiiiiiiiii")
        wide = _pixel_width_estimate("MMMMMMMMMM")
        self.assertLess(narrow, wide)

    def test_typical_title(self):
        px = _pixel_width_estimate("Warehouse Software | Example Co")
        self.assertGreater(px, 200)
        self.assertLess(px, 600)


class KeywordStuffingTests(unittest.TestCase):
    def test_natural_sentence(self):
        score = _keyword_stuff_score("A well-written description of the product and its benefits.")
        self.assertLess(score, 0.35)

    def test_keyword_list(self):
        score = _keyword_stuff_score("software, hosting, backups, monitoring, support, updates, security, reports")
        self.assertGreater(score, 0.35)


class MetaRuleCheckTests(unittest.TestCase):
    def test_pass_good_meta(self):
        site = _site()
        pm = _page(
            meta="This is a well-written meta description about the page topic, explaining it clearly for search engines and humans alike with good details.",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        statuses = {r.rule: r.status for r in results}
        self.assertEqual(statuses.get("meta-length"), "pass")

    def test_fail_missing_meta(self):
        site = _site()
        pm = _page(meta=None)
        results = check_meta_rules(pm, site, site.meta_rules)
        rules = {r.rule: r.status for r in results}
        self.assertEqual(rules["meta-missing"], "fail")

    def test_fail_too_long(self):
        site = _site()
        pm = _page(meta="x" * 170)
        results = check_meta_rules(pm, site, site.meta_rules)
        statuses = {r.rule: r.status for r in results}
        self.assertEqual(statuses["meta-length"], "fail")

    def test_warn_too_short(self):
        site = _site()
        pm = _page(meta="Short meta here about the topic.")
        results = check_meta_rules(pm, site, site.meta_rules)
        length_result = next(r for r in results if r.rule == "meta-length")
        self.assertIn(length_result.status, ("warn", "fail"))

    def test_fail_product_required(self):
        site = _site()
        pm = _page(
            url="https://www.example.com/",
            path="/",
            meta="A description without the product name mentioned anywhere at all in the full sentence here.",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        product_result = next(r for r in results if r.rule == "meta-product")
        self.assertEqual(product_result.status, "fail")

    def test_pass_product_optional(self):
        site = _site()
        pm = _page(
            url="https://www.example.com/about/",
            path="/about/",
            meta="About our team and their experience in the industry with great skills and knowledge for the clients.",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        product_result = next(r for r in results if r.rule == "meta-product")
        self.assertEqual(product_result.status, "pass")

    def test_fail_duplicate_meta(self):
        site = _site()
        pm = _page(meta="Shared description across multiple pages on the site.")
        all_metas = {
            "https://www.example.com/page/": "Shared description across multiple pages on the site.",
            "https://www.example.com/other/": "Shared description across multiple pages on the site.",
        }
        results = check_meta_rules(pm, site, site.meta_rules, all_metas=all_metas)
        unique_result = next(r for r in results if r.rule == "meta-unique")
        self.assertEqual(unique_result.status, "fail")

    def test_fail_duplicate_meta_tag(self):
        site = _site()
        pm = _page(meta_tag_count=2)
        results = check_meta_rules(pm, site, site.meta_rules)
        dup_result = next(r for r in results if r.rule == "meta-duplicate-tag")
        self.assertEqual(dup_result.status, "fail")

    def test_warn_double_quotes(self):
        site = _site()
        pm = _page(meta='A description with "double quotes" inside it that could cause display problems in SERPs.')
        results = check_meta_rules(pm, site, site.meta_rules)
        char_results = [r for r in results if r.rule == "meta-special-chars"]
        self.assertTrue(any(r.status == "warn" for r in char_results))

    def test_skip_noindex_page(self):
        site = _site()
        pm = _page(robots_directives=["noindex", "follow"], in_sitemap=False)
        results = check_meta_rules(pm, site, site.meta_rules)
        self.assertTrue(any(r.rule == "noindex" and r.status == "skip" for r in results))
        self.assertFalse(any(r.rule == "meta-length" for r in results))

    def test_fail_noindex_in_sitemap(self):
        site = _site()
        pm = _page(robots_directives=["noindex", "follow"], in_sitemap=True)
        results = check_meta_rules(pm, site, site.meta_rules)
        self.assertTrue(any(r.rule == "sitemap-noindex" and r.status == "fail" for r in results))

    def test_skip_redirect(self):
        site = _site()
        pm = _page(is_redirect=True)
        results = check_meta_rules(pm, site, site.meta_rules)
        self.assertTrue(any(r.rule == "redirect" and r.status == "skip" for r in results))
        self.assertFalse(any(r.rule == "meta-length" for r in results))


class TitleRuleTests(unittest.TestCase):
    def test_pass_good_title(self):
        site = _site()
        pm = _page(title="Example Software Tools | Test Co")
        results = check_meta_rules(pm, site, site.meta_rules)
        title_len = next(r for r in results if r.rule == "title-length")
        self.assertEqual(title_len.status, "pass")

    def test_fail_title_too_long(self):
        site = _site()
        pm = _page(title="A" * 75 + " | Test Co")
        results = check_meta_rules(pm, site, site.meta_rules)
        title_len = next(r for r in results if r.rule == "title-length")
        self.assertEqual(title_len.status, "fail")

    def test_fail_missing_title(self):
        site = _site()
        pm = _page(title="")
        results = check_meta_rules(pm, site, site.meta_rules)
        self.assertTrue(any(r.rule == "title-missing" and r.status == "fail" for r in results))

    def test_warn_title_equals_h1(self):
        site = _site()
        pm = _page(title="Exact Same Heading", h1s=["Exact Same Heading"])
        results = check_meta_rules(pm, site, site.meta_rules)
        h1_match = [r for r in results if r.rule == "title-h1-match"]
        self.assertTrue(any(r.status == "warn" for r in h1_match))

    def test_no_warn_title_differs_from_h1(self):
        site = _site()
        pm = _page(title="Page Topic | Test Co", h1s=["Page Topic Heading"])
        results = check_meta_rules(pm, site, site.meta_rules)
        h1_match = [r for r in results if r.rule == "title-h1-match"]
        self.assertFalse(any(r.status == "warn" for r in h1_match))

    def test_homepage_title_can_be_the_category(self):
        site = _site()
        pm = _page(
            url="https://www.example.com/",
            path="/",
            title="Example Software Tools | Test Co",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        title_product = [r for r in results if r.rule == "title-product"]
        self.assertFalse(any(r.status == "fail" for r in title_product))

    def test_fail_product_missing_on_product_page(self):
        site = _site()
        pm = _page(
            url="https://www.example.com/product/",
            path="/product/",
            title="Welcome to Our Website | Test Co",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        title_product = [r for r in results if r.rule == "title-product"]
        self.assertTrue(any(r.status == "fail" for r in title_product))

    def test_long_legal_name_uses_short_brand(self):
        site = _site(
            name="Example Consulting Group",
            meta_rules=MetaRules(
                product_required_pages=["/", "/product/"],
                brand_suffix="Example Consulting Group",
            ),
        )
        pm = _page(
            url="https://www.example.com/about/",
            path="/about/",
            title="About Example Consulting | Example",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        brand = [r for r in results if r.rule == "title-brand-format"]
        self.assertFalse(any(r.status == "warn" for r in brand))

    def test_redirect_is_not_a_duplicate_title(self):
        from aeo_audit.meta import _is_non_indexable

        home = _page(url="https://www.example.com/", path="/", title="Example Software Tools | Test Co")
        redirect = _page(url="https://www.example.com/lp", path="/lp", title="Example Software Tools | Test Co", is_redirect=True)
        pages = [pm for pm in (home, redirect) if not _is_non_indexable(pm)]
        titles = {pm.url: pm.title for pm in pages}
        results = check_meta_rules(home, _site(), _site().meta_rules, all_titles=titles)
        unique = [r for r in results if r.rule == "title-unique"]
        self.assertFalse(any(r.status == "fail" for r in unique))

    def test_fail_duplicate_title(self):
        site = _site()
        pm = _page(title="Same Title | Test Co")
        all_titles = {
            "https://www.example.com/page/": "Same Title | Test Co",
            "https://www.example.com/other/": "Same Title | Test Co",
        }
        results = check_meta_rules(pm, site, site.meta_rules, all_titles=all_titles)
        unique = [r for r in results if r.rule == "title-unique"]
        self.assertTrue(any(r.status == "fail" for r in unique))

    def test_warn_brand_missing(self):
        site = _site()
        pm = _page(title="Page Topic Without Brand Suffix")
        results = check_meta_rules(pm, site, site.meta_rules)
        brand = [r for r in results if r.rule == "title-brand-format"]
        self.assertTrue(any(r.status == "warn" for r in brand))


class SpellingAndClaimTests(unittest.TestCase):
    def test_spelling_fail(self):
        rules = MetaRules(spelling_rules={"WidgetPro": "Widget Pro"})
        site = _site(meta_rules=rules)
        pm = _page(meta="Great performance with WidgetPro integration for teams that need reliable software and clear support every day.")
        results = check_meta_rules(pm, site, rules)
        spelling = [r for r in results if r.rule == "meta-spelling"]
        self.assertTrue(any(r.status == "fail" for r in spelling))

    def test_spelling_pass(self):
        rules = MetaRules(spelling_rules={"WidgetPro": "Widget Pro"})
        site = _site(meta_rules=rules)
        pm = _page(meta="Great performance with Widget Pro integration for teams that need reliable software and clear support every day.")
        results = check_meta_rules(pm, site, rules)
        spelling = [r for r in results if r.rule == "meta-spelling"]
        self.assertEqual(len(spelling), 0)

    def test_superlative_warn(self):
        rules = MetaRules(banned_superlatives=["industry-leading"])
        site = _site(meta_rules=rules)
        pm = _page(meta="We are industry-leading experts in software support and reliable hosting for growing teams.")
        results = check_meta_rules(pm, site, rules)
        sup = [r for r in results if r.rule == "meta-superlative"]
        self.assertTrue(any(r.status == "warn" for r in sup))


class OGTagTests(unittest.TestCase):
    def test_warn_missing_og_description(self):
        site = _site()
        pm = _page(og_description="")
        results = check_meta_rules(pm, site, site.meta_rules)
        og = [r for r in results if r.rule == "og-description"]
        self.assertTrue(any(r.status == "warn" for r in og))

    def test_warn_og_title_mismatch(self):
        site = _site()
        pm = _page(title="Real Title | Test Co", og_title="Different OG Title")
        results = check_meta_rules(pm, site, site.meta_rules)
        og = [r for r in results if r.rule == "og-title"]
        self.assertTrue(any(r.status == "warn" for r in og))

    def test_pass_og_matches(self):
        site = _site()
        pm = _page(
            title="Page Topic | Test Co",
            og_title="Page Topic | Test Co",
            meta="Good meta description here with enough characters to pass the length check easily.",
            og_description="Good meta description here with enough characters to pass the length check easily.",
        )
        results = check_meta_rules(pm, site, site.meta_rules)
        og_desc = next(r for r in results if r.rule == "og-description")
        og_title = next(r for r in results if r.rule == "og-title")
        self.assertEqual(og_desc.status, "pass")
        self.assertEqual(og_title.status, "pass")


class CityRuleTests(unittest.TestCase):
    def test_warn_when_city_required_but_missing(self):
        rules = MetaRules(require_city=True, city_terms=["Springfield", "Riverside"])
        site = _site(meta_rules=rules)
        pm = _page(meta="Our amazing services for businesses across the region with great quality and support for all needs.")
        results = check_meta_rules(pm, site, rules)
        city = [r for r in results if r.rule == "meta-city"]
        self.assertTrue(any(r.status == "warn" for r in city))

    def test_pass_when_city_present(self):
        rules = MetaRules(require_city=True, city_terms=["Springfield"])
        site = _site(meta_rules=rules)
        pm = _page(meta="Our amazing Springfield-based services for businesses across the region with quality and support for needs.")
        results = check_meta_rules(pm, site, rules)
        city = [r for r in results if r.rule == "meta-city"]
        self.assertEqual(len(city), 0)

    def test_no_check_when_disabled(self):
        rules = MetaRules(require_city=False)
        site = _site(meta_rules=rules)
        pm = _page()
        results = check_meta_rules(pm, site, rules)
        city = [r for r in results if r.rule == "meta-city"]
        self.assertEqual(len(city), 0)


class ProposedLoaderTests(unittest.TestCase):
    def test_load_json(self):
        data = json.dumps([
            {"url": "https://example.com/", "meta": "Test meta", "title": "Test title"},
            {"url": "https://example.com/about/", "meta": "About meta"},
        ])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(data)
            f.flush()
            entries = load_proposed(Path(f.name))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].meta, "Test meta")
        self.assertEqual(entries[0].title, "Test title")
        self.assertEqual(entries[1].title, "")

    def test_load_csv(self):
        csv_text = "url,meta,title\nhttps://example.com/,Test meta,Test title\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_text)
            f.flush()
            entries = load_proposed(Path(f.name))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].url, "https://example.com/")

    def test_load_markdown(self):
        md = "| url | meta | title |\n| --- | --- | --- |\n| https://example.com/ | Test meta | Test title |\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(md)
            f.flush()
            entries = load_proposed(Path(f.name))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].meta, "Test meta")


if __name__ == "__main__":
    unittest.main()
