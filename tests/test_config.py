import unittest

from aeo_audit.config import (
    FleetError,
    MetaRules,
    Site,
    _domain_slug,
    _looks_like_domain_or_url,
    resolve_site,
    resolve_site_or_domain,
    site_from_domain,
)


class LooksDomainTests(unittest.TestCase):
    def test_plain_domain(self):
        self.assertTrue(_looks_like_domain_or_url("example.com"))

    def test_domain_with_www(self):
        self.assertTrue(_looks_like_domain_or_url("www.example.com"))

    def test_full_url(self):
        self.assertTrue(_looks_like_domain_or_url("https://www.example.com"))

    def test_slug(self):
        self.assertFalse(_looks_like_domain_or_url("example-site"))

    def test_slug_with_dash(self):
        self.assertFalse(_looks_like_domain_or_url("my-site"))

    def test_empty(self):
        self.assertFalse(_looks_like_domain_or_url(""))


class DomainSlugTests(unittest.TestCase):
    def test_plain_domain(self):
        self.assertEqual(_domain_slug("example.com"), "example.com")

    def test_strips_www(self):
        self.assertEqual(_domain_slug("https://www.example.com"), "example.com")

    def test_url_with_path(self):
        self.assertEqual(_domain_slug("https://www.example.com/page"), "example.com")

    def test_subdomain(self):
        self.assertEqual(_domain_slug("https://blog.example.com"), "blog.example.com")


class SiteFromDomainTests(unittest.TestCase):
    def test_basic(self):
        site = site_from_domain("example.com")
        self.assertEqual(site.slug, "example.com")
        self.assertEqual(site.url, "https://example.com")
        self.assertEqual(site.origin, "https://example.com")
        self.assertEqual(site.name, "example.com")
        self.assertEqual(site.product, "")
        self.assertIsInstance(site.meta_rules, MetaRules)

    def test_with_entity(self):
        site = site_from_domain("example.com", entity="Acme Widget")
        self.assertEqual(site.product, "Acme Widget")
        self.assertEqual(site.name, "Acme Widget")

    def test_full_url(self):
        site = site_from_domain("https://www.example.com")
        self.assertEqual(site.origin, "https://www.example.com")
        self.assertEqual(site.slug, "example.com")

    def test_http_url(self):
        site = site_from_domain("http://legacy.example.com")
        self.assertEqual(site.origin, "http://legacy.example.com")

    def test_default_rules(self):
        site = site_from_domain("example.com")
        self.assertEqual(site.meta_rules.product_required_pages, ["/"])
        self.assertEqual(site.meta_rules.spelling_rules, {})
        self.assertEqual(site.meta_rules.banned_superlatives, [])


class ResolveSiteOrDomainTests(unittest.TestCase):
    def test_unknown_domain_creates_adhoc(self):
        site = resolve_site_or_domain("totally-new-site.example.org")
        self.assertEqual(site.slug, "totally-new-site.example.org")
        self.assertEqual(site.origin, "https://totally-new-site.example.org")

    def test_unknown_domain_with_entity(self):
        site = resolve_site_or_domain(
            "acmewidgets.com", entity="Acme Widget Pro"
        )
        self.assertEqual(site.product, "Acme Widget Pro")
        self.assertEqual(site.name, "Acme Widget Pro")

    def test_unknown_slug_raises(self):
        with self.assertRaises(FleetError):
            resolve_site_or_domain("no-such-slug")

    def test_full_url_creates_adhoc(self):
        site = resolve_site_or_domain("https://www.newsite.io")
        self.assertEqual(site.slug, "newsite.io")
        self.assertEqual(site.origin, "https://www.newsite.io")


if __name__ == "__main__":
    unittest.main()
