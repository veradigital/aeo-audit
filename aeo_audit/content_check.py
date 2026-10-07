"""Content quality checks — word count, answer-first, headings, FAQ, NAP, links, readability, duplicates."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from aeo_audit.config import Site
from aeo_audit.crawl import PageData
from aeo_audit.http import Check, all_tags, jsonld_types

WORD_COUNT_THRESHOLDS = {
    "homepage": 300,
    "service": 500,
    "blog": 800,
    "product": 400,
    "about": 300,
    "contact": 100,
    "faq": 300,
    "default": 300,
}


def _page_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if path in ("/", ""):
        return "homepage"
    if "/blog/" in path or "/post/" in path or "/article/" in path:
        return "blog"
    if "/about" in path:
        return "about"
    if "/contact" in path:
        return "contact"
    if "/faq" in path:
        return "faq"
    if "/product" in path or "/inventory" in path:
        return "product"
    if any(kw in path for kw in ("/service", "/solution", "/what-we")):
        return "service"
    return "default"


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_n_words(html: str, n: int = 50) -> str:
    text = _strip_html(html)
    words = text.split()[:n]
    return " ".join(words)


def _avg_sentence_len(text: str) -> float:
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 0
    return sum(len(s.split()) for s in sentences) / len(sentences)


def _long_word_pct(text: str) -> float:
    words = text.split()
    if not words:
        return 0
    return sum(1 for w in words if len(w) > 12) / len(words)


def _faq_schema_questions(html: str) -> list[str]:
    """Extract questions from FAQPage JSON-LD."""
    import json
    blobs = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.I | re.S,
    )
    questions: list[str] = []
    for blob in blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        items = []
        if isinstance(data, dict):
            if data.get("@type") == "FAQPage":
                items = data.get("mainEntity", [])
            for node in (data.get("@graph") or []):
                if isinstance(node, dict) and node.get("@type") == "FAQPage":
                    items.extend(node.get("mainEntity", []))
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    q = item.get("name", "")
                    if q:
                        questions.append(q)
    return questions


def _visible_questions(html: str) -> list[str]:
    """Extract visible FAQ-like question text from headings and accordion labels."""
    questions: list[str] = []
    for tag in ("h2", "h3", "h4", "h5"):
        for text in all_tags(html, rf"<{tag}[^>]*>(.*?)</{tag}>"):
            if text.strip().endswith("?"):
                questions.append(text.strip())
    for btn in re.findall(r"<button[^>]*>(.*?)</button>", html, re.I | re.S):
        clean = re.sub(r"<[^>]+>", "", btn).strip()
        if clean.endswith("?") or len(clean) > 15:
            questions.append(clean)
    return questions


def _find_outdated(text: str) -> list[str]:
    """Flag obviously outdated years or price patterns."""
    import datetime
    current_year = datetime.date.today().year
    years = re.findall(r"\b(20[12]\d)\b", text)
    outdated: list[str] = []
    for y in years:
        if int(y) < current_year - 1:
            outdated.append(y)
    price_patterns = re.findall(r"\$[\d,]+(?:\.\d{2})?(?:\s*/\s*(?:mo|month|year|yr))?", text)
    return outdated


def _text_fingerprint(text: str) -> str:
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
    return " ".join(sorted(set(words[:100])))


def content_checks(
    site: Site,
    pages: list[PageData],
    page_html: dict[str, str] | None = None,
) -> list[Check]:
    checks: list[Check] = []
    html_map = page_html or {}
    fingerprints: dict[str, str] = {}

    for page in pages:
        if page.status >= 400:
            continue

        path = urlparse(page.url).path
        prefix = f"content:{path}"
        ptype = _page_type(page.url)
        html = html_map.get(page.url, "")

        threshold = WORD_COUNT_THRESHOLDS.get(ptype, WORD_COUNT_THRESHOLDS["default"])
        if page.word_count < threshold:
            if page.word_count < threshold // 2:
                checks.append(Check(
                    f"{prefix}:thin",
                    "fail",
                    f"Thin content: {path}",
                    f"{page.word_count} words ({ptype} needs {threshold}+)",
                    "Very thin pages are unlikely to rank or be cited.",
                    f"Expand to at least {threshold} words of useful content.",
                ))
            else:
                checks.append(Check(
                    f"{prefix}:thin",
                    "warn",
                    f"Word count: {path}",
                    f"{page.word_count} words ({ptype} target {threshold}+)",
                    "Below the typical word count for this page type.",
                    "Add more substantive content.",
                ))

        if html:
            opening = _first_n_words(html, 50)
            has_question_words = any(w in opening.lower() for w in ("is", "are", "does", "can", "what", "how", "why"))
            has_definitive = any(w in opening.lower() for w in ("is a", "is the", "are the", "provides", "offers", "helps"))
            if not has_definitive and ptype in ("service", "product", "blog", "faq"):
                checks.append(Check(
                    f"{prefix}:answer-first",
                    "warn",
                    f"Answer-first opening: {path}",
                    f'First 50 words: "{opening[:100]}..."',
                    "Pages that answer the main question in the first 50 words get cited more by AI.",
                    "Lead with a direct answer, then elaborate.",
                ))

        if page.headings:
            h1_count = len(page.headings.get("h1", []))
            h2_count = len(page.headings.get("h2", []))
            if h1_count > 1:
                checks.append(Check(
                    f"{prefix}:multi-h1",
                    "warn",
                    f"Multiple H1s: {path}",
                    f"{h1_count} H1 tags",
                    "More than one H1 dilutes the page's primary statement.",
                    "Use one H1, convert others to H2.",
                ))
            if page.word_count > 500 and h2_count == 0:
                checks.append(Check(
                    f"{prefix}:no-subheadings",
                    "warn",
                    f"No subheadings: {path}",
                    f"{page.word_count} words with no H2",
                    "Long content without subheadings is hard to scan and cite.",
                    "Break content into sections with descriptive H2s.",
                ))

        if html and ptype == "faq":
            schema_qs = _faq_schema_questions(html)
            visible_qs = _visible_questions(html)
            if schema_qs and not visible_qs:
                checks.append(Check(
                    f"{prefix}:faq-invisible",
                    "fail",
                    f"FAQ schema without visible questions: {path}",
                    f"{len(schema_qs)} schema questions, 0 visible",
                    "FAQ schema must match visible page content.",
                    "Make all FAQ schema questions visible on the page.",
                ))
            elif schema_qs:
                missing_vis = []
                for sq in schema_qs:
                    sq_lower = sq.lower().strip().rstrip("?")
                    found = any(sq_lower in vq.lower() for vq in visible_qs)
                    if not found:
                        missing_vis.append(sq)
                if missing_vis:
                    checks.append(Check(
                        f"{prefix}:faq-mismatch",
                        "warn",
                        f"FAQ schema/visible mismatch: {path}",
                        f"{len(missing_vis)} schema questions not found visibly: {missing_vis[0][:60]}...",
                        "Schema questions should be visible on the page.",
                        "Add the missing questions to the visible FAQ.",
                    ))

        is_local = bool(site.city) or bool(site.service_area)
        if is_local and ptype in ("homepage", "service", "contact"):
            body_text = _strip_html(html) if html else (page.title or "") + " " + (page.meta_desc or "")
            low = body_text.lower()
            nap_items: dict[str, bool] = {}
            if site.name:
                nap_items["business name"] = site.name.lower() in low
            if site.phone:
                nap_items["phone"] = site.phone.replace("-", "").replace(" ", "") in low.replace("-", "").replace(" ", "")
            if site.city:
                nap_items["city"] = site.city.lower().split(",")[0] in low
            for area in site.service_area[:3]:
                nap_items[f"area:{area}"] = area.lower() in low

            missing_nap = [k for k, v in nap_items.items() if not v]
            if missing_nap:
                checks.append(Check(
                    f"{prefix}:local-nap",
                    "warn",
                    f"Local signals: {path}",
                    f"Missing: {', '.join(missing_nap)}",
                    "Local pages should mention the business name, phone and service area.",
                    "Add NAP and service area mentions naturally.",
                ))

        internal_out = len([l for l in page.internal_links if urlparse(l).path != path])
        if internal_out == 0 and ptype not in ("contact",):
            checks.append(Check(
                f"{prefix}:orphan-out",
                "warn",
                f"No outgoing internal links: {path}",
                "0 internal links to other pages",
                "Pages without internal links are poorly connected.",
                "Add contextual links to related service/product pages.",
            ))

        if html:
            body_text = _strip_html(html)
            outdated = _find_outdated(body_text)
            if outdated:
                checks.append(Check(
                    f"{prefix}:outdated",
                    "warn",
                    f"Outdated references: {path}",
                    f"Years found: {', '.join(sorted(set(outdated)))}",
                    "Outdated dates reduce trust.",
                    "Update or remove outdated year references.",
                ))

            avg_sent = _avg_sentence_len(body_text)
            if avg_sent > 25:
                checks.append(Check(
                    f"{prefix}:readability",
                    "warn",
                    f"Readability: {path}",
                    f"Avg sentence length {avg_sent:.0f} words",
                    "Long sentences hurt readability and AI extraction.",
                    "Break long sentences. Target 15-20 words average.",
                ))

        fp = _text_fingerprint(page.title + " " + (page.meta_desc or ""))
        for prev_url, prev_fp in fingerprints.items():
            overlap = len(set(fp.split()) & set(prev_fp.split()))
            total = max(len(set(fp.split())), 1)
            if overlap / total > 0.8:
                checks.append(Check(
                    f"{prefix}:near-dup",
                    "warn",
                    f"Near-duplicate: {path}",
                    f"Very similar to {urlparse(prev_url).path}",
                    "Near-duplicate content confuses search engines.",
                    "Differentiate the content or consolidate pages.",
                ))
                break
        fingerprints[page.url] = fp

    key_page_urls = {site.origin + p for p in site.key_pages if p != "/"}
    for kp_url in key_page_urls:
        inbound = sum(
            1 for p in pages
            if any(kp_url.rstrip("/") in l for l in p.internal_links)
            and p.url != kp_url
        )
        if inbound == 0:
            checks.append(Check(
                f"content:orphan:{urlparse(kp_url).path}",
                "warn",
                f"Orphan key page: {urlparse(kp_url).path}",
                "No internal links pointing to this key page",
                "Key service pages need internal links for discovery and authority.",
                "Add links from the homepage and related pages.",
            ))

    return checks
