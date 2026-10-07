"""Focus keyphrase checks — placement, density, cannibalization, GSC mismatch."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from aeo_audit.config import Site, PageKeyphrase
from aeo_audit.crawl import PageData
from aeo_audit.http import Check, all_tags, first_tag

STUFFING_THRESHOLD = 0.035
MIN_DENSITY = 0.005


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_paragraph(html: str) -> str:
    m = re.search(r"<p[^>]*>(.*?)</p>", html, re.I | re.S)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1))
        return re.sub(r"\s+", " ", text).strip()
    return ""


def _density(text: str, phrase: str) -> float:
    if not text or not phrase:
        return 0.0
    words = text.lower().split()
    phrase_words = phrase.lower().split()
    if not words or not phrase_words:
        return 0.0
    count = 0
    phrase_len = len(phrase_words)
    for i in range(len(words) - phrase_len + 1):
        if words[i:i + phrase_len] == phrase_words:
            count += 1
    return (count * phrase_len) / len(words) if words else 0.0


def keyphrase_for_page(site: Site, path: str, gsc_top_query: str = "") -> str:
    """Resolve the focus keyphrase: inventory config > GSC top query > empty."""
    for pk in site.page_keyphrases:
        if pk.path.rstrip("/") == path.rstrip("/"):
            return pk.keyphrase
    return gsc_top_query


def check_keyphrase_placement(
    keyphrase: str,
    page: PageData,
    html: str = "",
) -> list[Check]:
    """Check keyphrase placement in title, meta, H1, slug, first paragraph, subheading."""
    if not keyphrase:
        return [Check(
            f"kp:{page.url}:missing",
            "warn",
            f"Focus keyphrase: {page.url}",
            "No keyphrase set",
            "Without a target keyphrase, on-page optimization cannot be measured.",
            "Set a keyphrase in inventory page_keyphrases or let GSC suggest one.",
        )]

    checks: list[Check] = []
    kp_low = keyphrase.lower()
    prefix = f"kp:{urlparse(page.url).path}"

    in_title = kp_low in (page.title or "").lower()
    in_meta = kp_low in (page.meta_desc or "").lower()
    in_h1 = kp_low in (page.h1 or "").lower()
    slug = urlparse(page.url).path.lower().replace("-", " ").replace("/", " ")
    in_slug = kp_low in slug

    first_para = _first_paragraph(html) if html else ""
    in_first_para = kp_low in first_para.lower() if first_para else False

    subheadings: list[str] = []
    for level in ("h2", "h3", "h4"):
        subheadings.extend(page.headings.get(level, []))
    in_subheading = any(kp_low in h.lower() for h in subheadings)

    placements = {
        "title": in_title,
        "meta": in_meta,
        "H1": in_h1,
        "slug": in_slug,
        "first paragraph": in_first_para,
        "subheading": in_subheading,
    }
    present = [k for k, v in placements.items() if v]
    missing = [k for k, v in placements.items() if not v]

    if len(present) >= 5:
        checks.append(Check(
            f"{prefix}:placement",
            "pass",
            f"Keyphrase placement: {keyphrase}",
            f"Found in: {', '.join(present)}",
        ))
    elif len(present) >= 3:
        checks.append(Check(
            f"{prefix}:placement",
            "warn",
            f"Keyphrase placement: {keyphrase}",
            f"Found in: {', '.join(present)}. Missing: {', '.join(missing)}",
            "The keyphrase is partially placed but missing from key locations.",
            f"Add '{keyphrase}' naturally to: {', '.join(missing)}.",
        ))
    else:
        checks.append(Check(
            f"{prefix}:placement",
            "fail",
            f"Keyphrase placement: {keyphrase}",
            f"Only in: {', '.join(present) or 'nowhere'}. Missing: {', '.join(missing)}",
            "The page does not target its keyphrase in enough locations.",
            f"Place '{keyphrase}' in title, meta, H1, first paragraph and at least one subheading.",
        ))

    body_text = _strip_html(html) if html else ""
    if body_text:
        density = _density(body_text, keyphrase)
        if density > STUFFING_THRESHOLD:
            checks.append(Check(
                f"{prefix}:stuffing",
                "warn",
                f"Keyphrase density: {keyphrase}",
                f"{density:.1%} (threshold {STUFFING_THRESHOLD:.1%})",
                "Keyword stuffing can trigger a penalty.",
                "Reduce repetition; use synonyms and related terms.",
            ))
        elif density < MIN_DENSITY and len(body_text.split()) > 100:
            checks.append(Check(
                f"{prefix}:thin-kp",
                "warn",
                f"Keyphrase density: {keyphrase}",
                f"{density:.1%} — very low",
                "The keyphrase barely appears in the content.",
                "Mention the keyphrase naturally a few more times.",
            ))

    return checks


def check_cannibalization(
    site: Site,
    pages: list[PageData],
    gsc_queries: dict[str, str] | None = None,
) -> list[Check]:
    """Flag two pages targeting the same keyphrase."""
    checks: list[Check] = []
    kp_map: dict[str, list[str]] = {}

    for page in pages:
        path = urlparse(page.url).path
        gsc_q = (gsc_queries or {}).get(page.url, "")
        kp = keyphrase_for_page(site, path, gsc_q)
        if kp:
            kp_map.setdefault(kp.lower(), []).append(page.url)

    for kp, urls in kp_map.items():
        if len(urls) > 1:
            checks.append(Check(
                f"kp:cannibal:{kp}",
                "warn",
                f"Keyphrase cannibalization: {kp}",
                f"Targeted by {len(urls)} pages: {', '.join(urls[:4])}",
                "Multiple pages competing for the same keyphrase dilute ranking power.",
                "Consolidate into one primary page; differentiate or redirect the others.",
            ))

    return checks


def check_gsc_mismatch(
    site: Site,
    page_url: str,
    set_keyphrase: str,
    gsc_top_queries: list[tuple[str, int]] | None = None,
) -> list[Check]:
    """Flag mismatch between the configured keyphrase and actual GSC queries."""
    if not set_keyphrase or not gsc_top_queries:
        return []

    checks: list[Check] = []
    kp_low = set_keyphrase.lower()
    top = gsc_top_queries[:5]

    top_query = top[0][0] if top else ""
    if top_query and kp_low not in top_query.lower() and top_query.lower() not in kp_low:
        checks.append(Check(
            f"kp:gsc-mismatch:{page_url}",
            "warn",
            f"Keyphrase vs GSC: {page_url}",
            f'Set keyphrase "{set_keyphrase}" but top query is "{top_query}" ({top[0][1]} impressions)',
            "The page ranks for different terms than its focus keyphrase.",
            f'Consider changing the keyphrase to "{top_query}" or optimizing for both.',
        ))

    return checks
