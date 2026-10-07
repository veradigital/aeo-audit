"""Full-site crawl: follow internal links + sitemap, collect per-page SEO data."""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from aeo_audit.config import Site
from aeo_audit.http import Check, Fetch, abs_url, all_tags, fetch, first_tag, jsonld_types


DEFAULT_PAGE_CAP = 50
POLITENESS_DELAY = 1.0

SKIP_EXTENSIONS = {
    ".xml", ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".gz", ".mp3", ".mp4", ".avi", ".mov", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx",
}


def _is_page_url(url: str) -> bool:
    """Return False for URLs that are clearly not crawlable HTML pages."""
    path = urlparse(url).path.lower()
    for ext in SKIP_EXTENSIONS:
        if path.endswith(ext):
            return False
    if "/wp-admin/" in path or "/wp-json/" in path:
        return False
    return True


@dataclass
class PageData:
    url: str
    status: int
    final_url: str
    title: str = ""
    meta_desc: str = ""
    h1: str = ""
    canonical: str = ""
    noindex: bool = False
    schema_types: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    broken_internal: list[str] = field(default_factory=list)
    images_missing_alt: int = 0
    total_images: int = 0
    word_count: int = 0
    headings: dict[str, list[str]] = field(default_factory=dict)
    redirect_chain: str = ""


def _same_origin(url: str, origin: str) -> bool:
    return urlparse(url).netloc.lower().lstrip("www.") == urlparse(origin).netloc.lower().lstrip("www.")


def _normalize(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc}{path}"


def _extract_links(html: str, base_url: str) -> list[str]:
    raw = re.findall(r'<a\s[^>]*href=["\']([^"\'#]+)', html, re.I)
    out: list[str] = []
    for href in raw:
        full = urljoin(base_url, href)
        out.append(full.split("#")[0].split("?")[0])
    return out


def _extract_images(html: str) -> tuple[int, int]:
    imgs = re.findall(r"<img\s[^>]*?>", html, re.I)
    total = len(imgs)
    missing_alt = sum(1 for img in imgs if not re.search(r'\balt=["\'][^"\']+["\']', img, re.I))
    return total, missing_alt


def _extract_canonical(html: str) -> str:
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', html, re.I)
    return m.group(1) if m else ""


def _has_noindex(html: str, headers: dict[str, str]) -> bool:
    if "noindex" in headers.get("x-robots-tag", "").lower():
        return True
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        name_m = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        content_m = re.search(r'\bcontent\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if name_m and content_m and name_m.group(1).lower() in ("robots", "googlebot"):
            content = content_m.group(1).lower()
            if "noindex" in content or "none" in content:
                return True
    return False


def _extract_headings(html: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for level in range(1, 7):
        tag = f"h{level}"
        found = all_tags(html, rf"<{tag}[^>]*>(.*?)</{tag}>")
        if found:
            out[tag] = found
    return out


def _word_count(html: str) -> int:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text.split())


def _sitemap_urls(body: str, origin: str) -> list[str]:
    urls: list[str] = []
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return urls
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for loc in root.findall(".//sm:loc", ns):
        if loc.text:
            urls.append(loc.text.strip())
    for loc in root.findall(".//loc"):
        if loc.text and loc.text.strip() not in urls:
            urls.append(loc.text.strip())
    return [u for u in urls if _same_origin(u, origin)]


def _robots_txt_sitemaps(robots_body: str) -> list[str]:
    out: list[str] = []
    for line in robots_body.splitlines():
        if line.lower().startswith("sitemap:"):
            out.append(line.split(":", 1)[1].strip())
    return out


def _is_allowed_by_robots(robots_body: str, path: str) -> bool:
    """Basic robots.txt check for our user-agent (treats * rules)."""
    if not robots_body.strip():
        return True
    disallowed = False
    for line in robots_body.splitlines():
        stripped = line.split("#", 1)[0].strip().lower()
        if stripped.startswith("user-agent:") and "*" in stripped:
            continue
        if stripped.startswith("disallow:"):
            rule = stripped.split(":", 1)[1].strip()
            if rule and path.startswith(rule):
                disallowed = True
        elif stripped.startswith("allow:"):
            rule = stripped.split(":", 1)[1].strip()
            if rule and path.startswith(rule):
                disallowed = False
    return not disallowed


def crawl_page(url: str) -> PageData:
    f = fetch(url)
    title = first_tag(f.body, r"<title[^>]*>(.*?)</title>")
    meta = first_tag(f.body, r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']')
    if not meta:
        meta = first_tag(f.body, r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']')
    h1s = all_tags(f.body, r"<h1[^>]*>(.*?)</h1>")
    canonical = _extract_canonical(f.body)
    noindex = _has_noindex(f.body, f.headers)
    schema = jsonld_types(f.body)
    total_img, missing_alt = _extract_images(f.body)
    headings = _extract_headings(f.body)
    wc = _word_count(f.body)
    redirect = ""
    if f.final_url and f.final_url != url:
        redirect = f"{url} -> {f.final_url}"

    return PageData(
        url=url,
        status=f.status,
        final_url=f.final_url,
        title=title,
        meta_desc=meta,
        h1=h1s[0] if h1s else "",
        canonical=canonical,
        noindex=noindex,
        schema_types=schema,
        internal_links=_extract_links(f.body, f.final_url or url),
        images_missing_alt=missing_alt,
        total_images=total_img,
        word_count=wc,
        headings=headings,
        redirect_chain=redirect,
    )


def crawl_site(
    site: Site,
    page_cap: int = DEFAULT_PAGE_CAP,
    politeness: float = POLITENESS_DELAY,
) -> tuple[list[PageData], list[Check]]:
    origin = site.origin
    visited: set[str] = set()
    queue: list[str] = [origin + "/"]
    pages: list[PageData] = []

    robots_f = fetch(abs_url(origin, "/robots.txt"))
    robots_body = robots_f.body if 200 <= robots_f.status < 400 else ""

    sitemap_urls_list: list[str] = []
    sm_urls = _robots_txt_sitemaps(robots_body) or [abs_url(origin, "/sitemap.xml"), abs_url(origin, "/sitemap_index.xml")]
    for sm_url in sm_urls:
        sm = fetch(sm_url)
        if 200 <= sm.status < 400:
            found = _sitemap_urls(sm.body, origin)
            if not found and "<sitemap" in sm.body:
                for sub_url in _sitemap_urls(sm.body, sm_url):
                    sub = fetch(sub_url)
                    if 200 <= sub.status < 400:
                        found.extend(_sitemap_urls(sub.body, origin))
            sitemap_urls_list.extend(found)

    for u in sitemap_urls_list:
        norm = _normalize(u)
        if norm not in visited and _same_origin(u, origin):
            queue.append(u)

    for path in site.key_pages:
        full = abs_url(origin, path)
        if _normalize(full) not in visited:
            queue.append(full)

    while queue and len(pages) < page_cap:
        url = queue.pop(0)
        norm = _normalize(url)
        if norm in visited:
            continue
        visited.add(norm)

        if not _is_page_url(url):
            continue

        path = urlparse(url).path
        if not _is_allowed_by_robots(robots_body, path):
            continue

        page = crawl_page(url)
        pages.append(page)

        if politeness > 0:
            time.sleep(politeness)

        for link in page.internal_links:
            link_norm = _normalize(link)
            if _same_origin(link, origin) and link_norm not in visited:
                queue.append(link)

    all_urls_set = {_normalize(p.url) for p in pages}
    for page in pages:
        for link in page.internal_links:
            if _same_origin(link, origin) and _normalize(link) not in all_urls_set:
                link_f = fetch(link)
                if link_f.status >= 400:
                    page.broken_internal.append(f"{link} ({link_f.status})")

    checks = _generate_checks(pages, site)
    return pages, checks


def _generate_checks(pages: list[PageData], site: Site) -> list[Check]:
    checks: list[Check] = []

    titles = Counter(p.title for p in pages if p.title)
    metas = Counter(p.meta_desc for p in pages if p.meta_desc)

    for page in pages:
        prefix = f"crawl:{urlparse(page.url).path}"

        if page.status >= 400:
            checks.append(Check(prefix + ":status", "fail", f"{page.url} status", f"{page.status}", "Broken page cannot be cited.", "Fix or redirect."))
            continue

        if page.status >= 300 and page.status < 400:
            checks.append(Check(prefix + ":redirect", "warn", f"{page.url} redirects", page.redirect_chain or f"{page.status}", "Redirect chains add latency.", "Update internal links to the final URL."))

        if page.noindex:
            checks.append(Check(prefix + ":noindex", "fail", f"{page.url} noindex", "noindex set", "Page will not appear in search.", "Remove noindex unless intentional."))

        if page.canonical and _normalize(page.canonical) != _normalize(page.final_url or page.url):
            checks.append(Check(prefix + ":canonical", "warn", f"{page.url} canonical mismatch", f"canonical={page.canonical} vs url={page.final_url or page.url}", "Canonical mismatch confuses indexing.", "Set canonical to the preferred URL."))

        if not page.title:
            checks.append(Check(prefix + ":title", "fail", f"{page.url} missing title", "No <title>", "Every page needs a title for search.", "Add a descriptive title."))
        elif titles[page.title] > 1:
            checks.append(Check(prefix + ":dup-title", "warn", f"{page.url} duplicate title", f'"{page.title}" used on {titles[page.title]} pages', "Duplicate titles dilute ranking signal.", "Make each title unique."))

        if not page.meta_desc:
            checks.append(Check(prefix + ":meta", "warn", f"{page.url} missing meta", "No meta description", "Thin descriptions reduce click-through and AI citation.", "Add a 120-156 char meta description."))
        elif metas[page.meta_desc] > 1:
            checks.append(Check(prefix + ":dup-meta", "warn", f"{page.url} duplicate meta", f"Same meta on {metas[page.meta_desc]} pages", "Duplicate metas make pages indistinguishable.", "Write unique meta per page."))

        if not page.h1:
            checks.append(Check(prefix + ":h1", "fail", f"{page.url} missing H1", "No H1", "Every page needs one clear H1.", "Add one H1."))

        if page.images_missing_alt > 0:
            checks.append(Check(prefix + ":alt", "warn", f"{page.url} images missing alt", f"{page.images_missing_alt}/{page.total_images} images lack alt text", "Missing alt hurts accessibility and image search.", "Add descriptive alt text."))

        if page.broken_internal:
            for bl in page.broken_internal[:5]:
                checks.append(Check(prefix + ":broken-link", "fail", f"{page.url} broken internal link", bl, "Broken links lose link equity and frustrate users.", "Fix or remove the link."))

        if not page.schema_types or page.schema_types == ["PARSE_FAIL"]:
            checks.append(Check(prefix + ":schema", "warn", f"{page.url} no valid schema", "No JSON-LD or parse failure", "Schema helps engines understand the page.", "Add appropriate JSON-LD."))

    return checks
