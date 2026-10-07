"""Per-page meta description and title audit.

Crawls the sitemap (or accepts proposed metas from a file), then runs
configurable pass/warn/fail rules on every indexable page.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from aeo_audit.config import data_root, MetaRules, Site, short_brand
from aeo_audit.http import Check, Fetch, abs_url, fetch, first_tag, all_tags

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PageMeta:
    """Extracted (or proposed) meta/title for a single URL."""

    url: str
    path: str = ""
    title: str = ""
    meta: str | None = None
    og_title: str = ""
    og_description: str = ""
    h1s: list[str] = field(default_factory=list)
    meta_tag_count: int = 1
    canonical: str = ""
    robots_directives: list[str] = field(default_factory=list)
    status: int = 200
    body_text: str = ""
    is_redirect: bool = False
    in_sitemap: bool = True


@dataclass
class RuleResult:
    """One rule evaluated on one page."""

    rule: str
    status: str          # pass | warn | fail | skip
    reason: str
    field: str = "meta"  # meta | title | page


# ---------------------------------------------------------------------------
# Sitemap crawl
# ---------------------------------------------------------------------------

def _extract_sitemap_urls(body: str) -> list[str]:
    """Pull <loc> URLs from a sitemap or sitemap index."""
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.I)


SITEMAP_CANDIDATES = [
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/wp-sitemap.xml",
    "/sitemap_index.xml.gz",
]


def _try_sitemap(url: str) -> list[str]:
    """Fetch one sitemap URL and return page URLs, following sitemap indexes."""
    top = fetch(url)
    if top.status < 200 or top.status >= 400:
        return []
    urls: list[str] = []
    if "<sitemap>" in top.body or "<sitemap " in top.body:
        for child_url in _extract_sitemap_urls(top.body):
            child = fetch(child_url)
            if 200 <= child.status < 400:
                urls.extend(_extract_sitemap_urls(child.body))
    else:
        urls.extend(_extract_sitemap_urls(top.body))
    return urls


_SKIP_EXTENSIONS = {
    ".xml", ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".gz", ".mp3", ".mp4",
}


def _is_page_url(url: str) -> bool:
    """Return False for URLs that are clearly not crawlable HTML pages."""
    path = urlparse(url).path.lower()
    for ext in _SKIP_EXTENSIONS:
        if path.endswith(ext):
            return False
    if "/wp-admin/" in path or "/wp-json/" in path:
        return False
    return True


def crawl_sitemap(site: Site, page_cap: int = 200) -> list[str]:
    """Fetch sitemap(s) and return all <loc> URLs (HTML pages only).

    Discovery order: robots.txt Sitemap: directive, then common paths
    (/sitemap_index.xml, /sitemap.xml, /wp-sitemap.xml).
    Non-page URLs (images, PDFs, XML) are filtered out.
    """
    origin = site.origin
    robots = fetch(abs_url(origin, "/robots.txt"))
    tried: set[str] = set()

    robot_sitemaps: list[str] = []
    if 200 <= robots.status < 400:
        for line in robots.body.splitlines():
            if line.lower().startswith("sitemap:"):
                robot_sitemaps.append(line.split(":", 1)[1].strip())

    all_urls: list[str] = []

    for sm_url in robot_sitemaps:
        if sm_url in tried:
            continue
        tried.add(sm_url)
        all_urls.extend(_try_sitemap(sm_url))

    if not all_urls:
        for path in SITEMAP_CANDIDATES:
            sm_url = abs_url(origin, path)
            if sm_url in tried:
                continue
            tried.add(sm_url)
            found = _try_sitemap(sm_url)
            if found:
                all_urls.extend(found)
                break

    filtered = [u for u in all_urls if _is_page_url(u)]
    seen: set[str] = set()
    unique: list[str] = []
    for u in filtered:
        norm = u.rstrip("/")
        if norm not in seen:
            seen.add(norm)
            unique.append(u)
        if len(unique) >= page_cap:
            break
    return unique


# ---------------------------------------------------------------------------
# Page-level extraction
# ---------------------------------------------------------------------------

def _extract_meta_description(html: str) -> tuple[str | None, int]:
    """Return (first meta description text or None, count of meta desc tags)."""
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
    ]
    all_matches: list[str] = []
    for pat in patterns:
        all_matches.extend(re.findall(pat, html, re.I | re.S))
    if not all_matches:
        return None, 0
    first = re.sub(r"\s+", " ", all_matches[0]).strip()
    return first, len(all_matches)


def _extract_og(html: str, prop: str) -> str:
    pat = rf'<meta[^>]+property=["\']og:{prop}["\'][^>]+content=["\'](.*?)["\']'
    m = re.search(pat, html, re.I | re.S)
    if not m:
        pat2 = rf'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:{prop}["\']'
        m = re.search(pat2, html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _extract_canonical(html: str) -> str:
    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']', html, re.I)
    if not m:
        m = re.search(r'<link[^>]+href=["\'](.*?)["\'][^>]+rel=["\']canonical["\']', html, re.I)
    return m.group(1).strip() if m else ""


def _extract_robots_directives(html: str) -> list[str]:
    directives: list[str] = []
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        name_m = re.search(r"""\bname\s*=\s*['"]([^'"]+)['"]""", tag, re.I)
        content_m = re.search(r"""\bcontent\s*=\s*['"]([^'"]+)['"]""", tag, re.I)
        if not name_m or not content_m:
            continue
        if name_m.group(1).lower() in {"robots", "googlebot"}:
            for tok in content_m.group(1).lower().split(","):
                directives.append(tok.strip())
    return directives


def _body_text(html: str) -> str:
    """Rough visible-text extraction for content-match heuristics."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_page(url: str, f: Fetch | None = None) -> PageMeta:
    """Fetch a URL and extract meta/title/OG/H1/robots signals."""
    if f is None:
        f = fetch(url)
    path = urlparse(url).path or "/"
    is_redirect = f.final_url and urlparse(f.final_url).path != path
    title = first_tag(f.body, r"<title[^>]*>(.*?)</title>")
    meta_text, meta_count = _extract_meta_description(f.body)
    canonical = _extract_canonical(f.body)
    robots_dirs = _extract_robots_directives(f.body)

    return PageMeta(
        url=url,
        path=path,
        title=title,
        meta=meta_text,
        og_title=_extract_og(f.body, "title"),
        og_description=_extract_og(f.body, "description"),
        h1s=all_tags(f.body, r"<h1[^>]*>(.*?)</h1>"),
        meta_tag_count=meta_count,
        canonical=canonical,
        robots_directives=robots_dirs,
        status=f.status,
        body_text=_body_text(f.body),
        is_redirect=is_redirect,
        in_sitemap=True,
    )


# ---------------------------------------------------------------------------
# Proposed meta loader (JSON / CSV / Markdown)
# ---------------------------------------------------------------------------

@dataclass
class ProposedEntry:
    url: str
    meta: str = ""
    title: str = ""


def _load_proposed_json(text: str) -> list[ProposedEntry]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = list(data.values()) if all(isinstance(v, dict) for v in data.values()) else [data]
    entries: list[ProposedEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("URL") or item.get("page") or "")
        meta = str(item.get("meta") or item.get("meta_description") or item.get("proposed") or item.get("description") or "")
        title = str(item.get("title") or item.get("seo_title") or "")
        if url and (meta or title):
            entries.append(ProposedEntry(url=url, meta=meta, title=title))
    return entries


def _load_proposed_csv(text: str) -> list[ProposedEntry]:
    reader = csv.DictReader(io.StringIO(text))
    entries: list[ProposedEntry] = []
    for row in reader:
        url = row.get("url") or row.get("URL") or row.get("page") or ""
        meta = row.get("meta") or row.get("meta_description") or row.get("proposed") or row.get("description") or ""
        title = row.get("title") or row.get("seo_title") or ""
        if url and (meta or title):
            entries.append(ProposedEntry(url=url.strip(), meta=meta.strip(), title=title.strip()))
    return entries


def _load_proposed_markdown(text: str) -> list[ProposedEntry]:
    """Parse a markdown table with url + meta (+ optional title) columns."""
    lines = [l.strip() for l in text.splitlines() if "|" in l]
    if len(lines) < 2:
        return []
    header = [c.strip().lower() for c in lines[0].split("|")]
    url_idx = meta_idx = title_idx = -1
    for i, h in enumerate(header):
        if h in ("url", "page", "page url"):
            url_idx = i
        elif h in ("meta", "meta_description", "proposed", "proposed meta", "description"):
            meta_idx = i
        elif h in ("title", "seo_title", "proposed title"):
            title_idx = i
    if url_idx < 0 or meta_idx < 0:
        return []
    entries: list[ProposedEntry] = []
    for line in lines[2:]:
        cols = line.split("|")
        if len(cols) <= max(url_idx, meta_idx):
            continue
        url = cols[url_idx].strip()
        meta = cols[meta_idx].strip()
        title = cols[title_idx].strip() if title_idx >= 0 and len(cols) > title_idx else ""
        if url.startswith("---") or not url:
            continue
        if url and (meta or title):
            entries.append(ProposedEntry(url=url, meta=meta, title=title))
    return entries


def load_proposed(path: Path) -> list[ProposedEntry]:
    text = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()
    if ext == ".json":
        return _load_proposed_json(text)
    if ext == ".csv":
        return _load_proposed_csv(text)
    if ext in (".md", ".markdown", ".txt"):
        return _load_proposed_markdown(text)
    try:
        return _load_proposed_json(text)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        return _load_proposed_csv(text)
    except Exception:
        pass
    return _load_proposed_markdown(text)


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------

def _is_noindex(pm: PageMeta) -> bool:
    return any(d in ("noindex", "none") for d in pm.robots_directives)


def _is_nofollow(pm: PageMeta) -> bool:
    return any(d in ("nofollow", "none") for d in pm.robots_directives)


def _is_non_indexable(pm: PageMeta) -> bool:
    """True if the page is noindex, redirected, or canonicalized elsewhere."""
    if _is_noindex(pm):
        return True
    if pm.is_redirect:
        return True
    if pm.canonical:
        own = pm.url.rstrip("/")
        can = pm.canonical.rstrip("/")
        if can and can != own and not can.endswith(pm.path.rstrip("/")):
            return True
    return False


def _normalize_path(url_or_path: str) -> str:
    if url_or_path.startswith("http"):
        return urlparse(url_or_path).path.rstrip("/") or "/"
    return url_or_path.rstrip("/") or "/"


def _pixel_width_estimate(text: str) -> int:
    """Rough pixel-width estimate. Average width per char varies by character
    class; this uses a simplified model similar to Moz/Yoast heuristics."""
    width = 0.0
    for ch in text:
        if ch in "MWm":
            width += 13.5
        elif ch in "wO":
            width += 11.5
        elif ch in "ABCDEFGHKNPQRSTUVXYZ":
            width += 10.0
        elif ch in "abcdeghknopqrstuvxyz0123456789":
            width += 8.5
        elif ch in "iIl|!":
            width += 4.5
        elif ch in "jftJ":
            width += 6.0
        elif ch in " ":
            width += 4.0
        elif ch in ".,;:'\"":
            width += 4.0
        elif ch in "-–—":
            width += 6.5
        else:
            width += 8.5
    return int(width)


def _focus_phrase(title: str, focus_phrases: dict[str, str], path: str) -> str:
    """Determine the focus phrase for this page: explicit override, or the
    longest multi-word segment before a pipe/dash separator in the title."""
    norm = _normalize_path(path)
    if norm in focus_phrases:
        return focus_phrases[norm]
    for key, val in focus_phrases.items():
        if _normalize_path(key) == norm:
            return val
    if "|" in title:
        return title.split("|")[0].strip()
    if " – " in title:
        return title.split(" – ")[0].strip()
    if " - " in title:
        return title.split(" - ")[0].strip()
    return title.strip()


def _keyword_stuff_score(text: str) -> float:
    """Heuristic: ratio of comma-separated fragments to total length.
    High ratios suggest keyword lists rather than natural sentences."""
    if not text:
        return 0.0
    commas = text.count(",")
    words = len(text.split())
    if words < 4:
        return 0.0
    return commas / words


def _has_differentiator(text: str) -> bool:
    """Check whether the meta contains a clear differentiator or CTA, not
    just a keyword list. Presence of a verb phrase or action word is a proxy."""
    action_words = (
        "learn", "discover", "get", "explore", "find", "see", "try", "start",
        "create", "build", "optimize", "improve", "modernize", "repair",
        "stabilize", "assess", "implement", "compare", "watch", "download",
        "contact", "request", "schedule", "enable", "unlock", "transform",
    )
    low = text.lower()
    return any(w in low for w in action_words)


# ---------------------------------------------------------------------------
# Rule runners
# ---------------------------------------------------------------------------

def check_meta_rules(
    pm: PageMeta,
    site: Site,
    rules: MetaRules,
    all_metas: dict[str, str | None] | None = None,
    all_titles: dict[str, str] | None = None,
) -> list[RuleResult]:
    """Run all meta-description rules on one page. Returns a list of results."""
    results: list[RuleResult] = []
    non_indexable = _is_non_indexable(pm)
    path = _normalize_path(pm.url)

    # --- Indexability issues (always reported) ---
    if _is_noindex(pm) and pm.in_sitemap:
        dirs = ", ".join(pm.robots_directives)
        results.append(RuleResult(
            "sitemap-noindex", "fail",
            f"Page is noindex ({dirs}) but listed in the sitemap",
            field="page",
        ))
    if _is_noindex(pm) and not pm.in_sitemap:
        results.append(RuleResult(
            "noindex", "skip",
            "Page is noindex; meta/title rules are N/A",
            field="page",
        ))
    if pm.is_redirect:
        results.append(RuleResult(
            "redirect", "skip",
            f"Page redirects to {pm.canonical or 'another URL'}; meta/title rules are N/A",
            field="page",
        ))
    canon_mismatch = False
    if pm.canonical:
        own = pm.url.rstrip("/")
        can = pm.canonical.rstrip("/")
        if can and can != own and not can.endswith(path.rstrip("/")):
            canon_mismatch = True
            results.append(RuleResult(
                "canonical-other", "skip",
                f"Canonical points to {pm.canonical}; meta/title rules are N/A",
                field="page",
            ))

    if non_indexable:
        return results

    # --- Meta: missing ---
    if pm.meta is None:
        results.append(RuleResult("meta-missing", "fail", "No meta description tag", field="meta"))
    else:
        meta = pm.meta
        n = len(meta)

        # --- Meta: length bands ---
        if n < rules.meta_len_fail_low:
            results.append(RuleResult("meta-length", "fail", f"{n} chars — below {rules.meta_len_fail_low} minimum", field="meta"))
        elif n < 100:
            results.append(RuleResult("meta-length", "warn", f"{n} chars — under 100, too short to be useful", field="meta"))
        elif n < rules.meta_len_warn_low:
            results.append(RuleResult("meta-length", "warn", f"{n} chars — under {rules.meta_len_warn_low} target", field="meta"))
        elif n <= rules.meta_len_target_high:
            results.append(RuleResult("meta-length", "pass", f"{n} chars (target {rules.meta_len_target_low}–{rules.meta_len_target_high})", field="meta"))
        elif n <= rules.meta_len_warn_high:
            results.append(RuleResult("meta-length", "warn", f"{n} chars — may be truncated on mobile (target ≤{rules.meta_len_target_high})", field="meta"))
        else:
            results.append(RuleResult("meta-length", "fail", f"{n} chars — exceeds {rules.meta_len_fail_high}, will be truncated", field="meta"))

        # --- Meta: product name ---
        product = (site.product.split("(")[0] if site.product else "").strip()
        if product:
            has_product = product.lower() in meta.lower()
            is_required = path in [_normalize_path(p) for p in rules.product_required_pages]
            if is_required and not has_product:
                results.append(RuleResult("meta-product", "fail", f"Product-defining page missing '{product}'", field="meta"))
            elif not is_required and not has_product:
                results.append(RuleResult("meta-product", "pass", f"Product name optional on this page type", field="meta"))
            else:
                results.append(RuleResult("meta-product", "pass", f"Contains '{product}'", field="meta"))

        # --- Meta: focus phrase ---
        focus = _focus_phrase(pm.title, rules.focus_phrases, pm.url)
        if focus and len(focus.split()) >= 2:
            if focus.lower() in meta.lower():
                results.append(RuleResult("meta-focus-phrase", "pass", f"Contains focus phrase '{focus}'", field="meta"))
            else:
                words = focus.lower().split()
                partial = sum(1 for w in words if w in meta.lower())
                if partial >= len(words) * 0.6:
                    results.append(RuleResult("meta-focus-phrase", "warn", f"Partial match for '{focus}' ({partial}/{len(words)} words)", field="meta"))
                else:
                    results.append(RuleResult("meta-focus-phrase", "warn", f"Missing focus phrase '{focus}'", field="meta"))

        # --- Meta: spelling rules ---
        for wrong, right in rules.spelling_rules.items():
            if wrong in meta:
                results.append(RuleResult("meta-spelling", "fail", f"'{wrong}' should be '{right}'", field="meta"))

        # --- Meta: claim phrasing ---
        if rules.claim_pattern:
            claim_rx = re.compile(rules.claim_pattern)
            if claim_rx.search(meta):
                results.append(RuleResult("meta-claims", "fail", f"Claim phrasing violation (pattern: {rules.claim_pattern})", field="meta"))

        # --- Meta: banned superlatives ---
        for sup in rules.banned_superlatives:
            if sup.lower() in meta.lower():
                results.append(RuleResult("meta-superlative", "warn", f"Unsupported superlative '{sup}'", field="meta"))

        # --- Meta: double quotes / special chars ---
        if '"' in meta:
            results.append(RuleResult("meta-special-chars", "warn", "Contains double quotes — may break HTML or display oddly in SERPs", field="meta"))
        if "'" in meta and "&" not in meta:
            pass  # straight apostrophes are common and usually fine
        for ch in ("<", ">"):
            if ch in meta:
                results.append(RuleResult("meta-special-chars", "warn", f"Contains unescaped '{ch}'", field="meta"))

        # --- Meta: keyword stuffing heuristic ---
        stuff_score = _keyword_stuff_score(meta)
        if stuff_score > 0.35:
            results.append(RuleResult("meta-keyword-stuffing", "warn", f"Looks like a keyword list (comma ratio {stuff_score:.2f})", field="meta"))
        elif not _has_differentiator(meta):
            results.append(RuleResult("meta-no-differentiator", "warn", "No clear differentiator or call to action", field="meta"))

        # --- Meta: content match heuristic ---
        if pm.body_text:
            meta_words = set(w.lower() for w in re.findall(r"\b[a-zA-Z]{4,}\b", meta))
            body_words = set(w.lower() for w in re.findall(r"\b[a-zA-Z]{4,}\b", pm.body_text[:3000]))
            h1_words = set()
            for h in pm.h1s:
                h1_words.update(w.lower() for w in re.findall(r"\b[a-zA-Z]{4,}\b", h))
            if meta_words:
                overlap = meta_words & (body_words | h1_words)
                ratio = len(overlap) / len(meta_words) if meta_words else 1.0
                if ratio < 0.3:
                    results.append(RuleResult("meta-content-match", "warn", f"Only {len(overlap)}/{len(meta_words)} key terms found in page body/H1", field="meta"))
                else:
                    results.append(RuleResult("meta-content-match", "pass", f"{len(overlap)}/{len(meta_words)} key terms match page content", field="meta"))

        # --- Meta: city / service area ---
        if rules.require_city and rules.city_terms:
            has_city = any(t.lower() in meta.lower() for t in rules.city_terms)
            if not has_city:
                results.append(RuleResult("meta-city", "warn", f"Missing city/service-area term ({', '.join(rules.city_terms)})", field="meta"))

        # --- Meta: auto-excerpt detection ---
        if pm.body_text and meta and len(meta) > 100:
            first_300 = pm.body_text[:300].lower().replace("\n", " ")
            if meta.lower()[:80] in first_300:
                results.append(RuleResult("meta-auto-excerpt", "warn", "Meta looks like an auto-generated excerpt of the page opening", field="meta"))

    # --- Meta: duplicate tag count ---
    if pm.meta_tag_count > 1:
        results.append(RuleResult("meta-duplicate-tag", "fail", f"{pm.meta_tag_count} meta description tags found (theme + SEO plugin conflict?)", field="meta"))

    # --- Meta: uniqueness across pages ---
    if all_metas and pm.meta:
        dupes = [u for u, m in all_metas.items() if m and m == pm.meta and u != pm.url]
        if dupes:
            results.append(RuleResult("meta-unique", "fail", f"Duplicate meta with: {', '.join(_normalize_path(d) for d in dupes)}", field="meta"))

    # --- OG tags ---
    if pm.meta is not None:
        if not pm.og_description:
            results.append(RuleResult("og-description", "warn", "Missing og:description", field="meta"))
        elif pm.og_description != pm.meta:
            if pm.og_description.lower().strip() != pm.meta.lower().strip():
                results.append(RuleResult("og-description", "warn", f"og:description differs from meta description", field="meta"))
            else:
                results.append(RuleResult("og-description", "pass", "og:description matches meta", field="meta"))
        else:
            results.append(RuleResult("og-description", "pass", "og:description matches meta", field="meta"))

    if pm.title:
        if not pm.og_title:
            results.append(RuleResult("og-title", "warn", "Missing og:title", field="title"))
        elif pm.og_title.lower().strip() != pm.title.lower().strip():
            results.append(RuleResult("og-title", "warn", "og:title differs from <title>", field="title"))
        else:
            results.append(RuleResult("og-title", "pass", "og:title matches <title>", field="title"))

    # ===== Title rules =====
    if not pm.title:
        results.append(RuleResult("title-missing", "fail", "No <title> tag", field="title"))
    else:
        t = pm.title
        tlen = len(t)
        tpx = _pixel_width_estimate(t)

        # --- Title: length ---
        if tlen < rules.title_len_fail_low:
            results.append(RuleResult("title-length", "fail", f"{tlen} chars — too short", field="title"))
        elif tlen < rules.title_len_warn_low:
            results.append(RuleResult("title-length", "warn", f"{tlen} chars — short", field="title"))
        elif tlen <= rules.title_len_target_high:
            results.append(RuleResult("title-length", "pass", f"{tlen} chars (target ≤{rules.title_len_target_high})", field="title"))
        elif tlen <= rules.title_len_fail_high:
            results.append(RuleResult("title-length", "warn", f"{tlen} chars — may be truncated (target ≤{rules.title_len_target_high})", field="title"))
        else:
            results.append(RuleResult("title-length", "fail", f"{tlen} chars — will be truncated (limit ~{rules.title_len_fail_high})", field="title"))

        # --- Title: pixel width ---
        if tpx > rules.title_pixel_limit:
            results.append(RuleResult("title-pixel-width", "warn", f"~{tpx}px estimated width — may be truncated (~{rules.title_pixel_limit}px limit)", field="title"))

        # --- Title: product name on the product page ---
        # The homepage title is the category. The product name stays in the
        # homepage description so this title does not copy the product page.
        if site.product:
            product = site.product.split("(")[0].strip()
            required = [_normalize_path(p) for p in rules.product_required_pages]
            if path in required and path != "/" and product.lower() not in t.lower():
                results.append(RuleResult("title-product", "fail", f"Product page title missing '{product}'", field="title"))

        # --- Title: short brand at the end ---
        if rules.brand_suffix:
            brand = short_brand(site)
            ends_with_brand = t.lower().rstrip().endswith(brand.lower())
            if not ends_with_brand:
                results.append(RuleResult("title-brand-format", "warn", f"Expected brand '{brand}' at end after separator", field="title"))

        # --- Title: unique ---
        if all_titles:
            dupes = [u for u, tt in all_titles.items() if tt == t and u != pm.url]
            if dupes:
                results.append(RuleResult("title-unique", "fail", f"Duplicate title with: {', '.join(_normalize_path(d) for d in dupes)}", field="title"))

        # --- Title: H1 word-for-word match ---
        if pm.h1s:
            for h1 in pm.h1s:
                if h1.strip().lower() == t.strip().lower():
                    results.append(RuleResult("title-h1-match", "warn", "Title is identical to H1 — they should share the phrase but not match exactly", field="title"))
                    break

        # --- Title: focus phrase near start ---
        focus = _focus_phrase(t, rules.focus_phrases, pm.url)
        if focus and len(focus.split()) >= 2:
            if "|" in t:
                before_sep = t.split("|")[0].strip()
                if focus.lower() not in before_sep.lower():
                    results.append(RuleResult("title-focus-position", "warn", f"Main phrase should appear before the separator", field="title"))

        # --- Title: spelling rules ---
        for wrong, right in rules.spelling_rules.items():
            if wrong in t:
                results.append(RuleResult("title-spelling", "fail", f"'{wrong}' should be '{right}'", field="title"))

    return results


# ---------------------------------------------------------------------------
# Full audit orchestration
# ---------------------------------------------------------------------------

def audit_site_metas(
    site: Site,
    proposed_file: Path | None = None,
    page_cap: int = 200,
) -> tuple[list[tuple[PageMeta, list[RuleResult]]], list[str]]:
    """Run the full meta/title audit. Returns (per-page results, warnings)."""
    rules = site.meta_rules
    warnings: list[str] = []

    if proposed_file:
        return _audit_proposed(site, proposed_file, rules, warnings)

    sitemap_urls = crawl_sitemap(site, page_cap=page_cap)
    if not sitemap_urls:
        warnings.append("Could not fetch sitemap; falling back to key_pages")
        sitemap_urls = [abs_url(site.origin, p) for p in site.key_pages]

    sitemap_set = {u.rstrip("/") for u in sitemap_urls}
    pages: list[PageMeta] = []
    for url in sitemap_urls:
        pm = extract_page(url)
        pm.in_sitemap = True
        pages.append(pm)

    comparable = [pm for pm in pages if not _is_non_indexable(pm)]
    all_metas = {pm.url: pm.meta for pm in comparable}
    all_titles = {pm.url: pm.title for pm in comparable}

    results: list[tuple[PageMeta, list[RuleResult]]] = []
    for pm in pages:
        checks = check_meta_rules(pm, site, rules, all_metas, all_titles)
        results.append((pm, checks))

    return results, warnings


def _audit_proposed(
    site: Site,
    proposed_file: Path,
    rules: MetaRules,
    warnings: list[str],
) -> tuple[list[tuple[PageMeta, list[RuleResult]]], list[str]]:
    """Check proposed metas from a file without fetching live pages."""
    entries = load_proposed(proposed_file)
    if not entries:
        warnings.append(f"No entries found in {proposed_file}")
        return [], warnings

    all_metas = {e.url: e.meta for e in entries}
    all_titles = {e.url: e.title for e in entries if e.title}

    results: list[tuple[PageMeta, list[RuleResult]]] = []
    for entry in entries:
        pm = PageMeta(
            url=entry.url,
            path=urlparse(entry.url).path or "/",
            title=entry.title,
            meta=entry.meta if entry.meta else None,
            in_sitemap=True,
        )
        checks = check_meta_rules(pm, site, rules, all_metas, all_titles)
        results.append((pm, checks))

    return results, warnings


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_meta_table(
    site: Site,
    results: list[tuple[PageMeta, list[RuleResult]]],
    warnings: list[str],
) -> None:
    p = w = f = 0
    for _, checks in results:
        for c in checks:
            if c.status == "pass":
                p += 1
            elif c.status == "warn":
                w += 1
            elif c.status == "fail":
                f += 1

    print(f"{site.display_name}  meta/title audit")
    print(f"pass {p}  warn {w}  fail {f}")
    for msg in warnings:
        print(f"  (!) {msg}")
    print()

    for pm, checks in results:
        path = _normalize_path(pm.url)
        statuses = [c.status for c in checks if c.status != "skip"]
        if any(s == "fail" for s in statuses):
            page_mark = "FAIL"
        elif any(s == "warn" for s in statuses):
            page_mark = "WARN"
        elif statuses:
            page_mark = "PASS"
        else:
            page_mark = "SKIP"
        meta_preview = (pm.meta or "(none)")[:60]
        print(f"{page_mark:4}  {path}")
        if pm.meta is not None:
            print(f"      meta ({len(pm.meta)} chars): {meta_preview}{'…' if pm.meta and len(pm.meta) > 60 else ''}")
        else:
            print(f"      meta: (none)")
        if pm.title:
            print(f"      title ({len(pm.title)} chars): {pm.title[:70]}")
        for c in checks:
            mark = c.status.upper()
            print(f"        {mark:4}  [{c.field}] {c.rule}: {c.reason}")
        print()


def markdown_meta_report(
    site: Site,
    results: list[tuple[PageMeta, list[RuleResult]]],
    warnings: list[str],
    proposed_file: str = "",
) -> str:
    p = w = f = 0
    for _, checks in results:
        for c in checks:
            if c.status == "pass":
                p += 1
            elif c.status == "warn":
                w += 1
            elif c.status == "fail":
                f += 1

    today = date.today().isoformat()
    mode = "proposed" if proposed_file else "live"
    lines = [
        f"# Meta/title audit — {site.display_name} — {today} ({mode})",
        "",
        f"Site: {site.origin}  ",
        f"Score: **{p} pass / {w} warn / {f} fail**  ",
    ]
    if proposed_file:
        lines.append(f"Source: `{proposed_file}`  ")
    for msg in warnings:
        lines.append(f"**Warning:** {msg}  ")
    lines += [
        "",
        f"Thresholds: meta {site.meta_rules.meta_len_target_low}–{site.meta_rules.meta_len_target_high} chars "
        f"(warn <{site.meta_rules.meta_len_warn_low}, fail <{site.meta_rules.meta_len_fail_low} or >{site.meta_rules.meta_len_fail_high}); "
        f"title ≤{site.meta_rules.title_len_target_high} chars "
        f"(fail >{site.meta_rules.title_len_fail_high})",
        "",
    ]

    for pm, checks in results:
        path = _normalize_path(pm.url)
        statuses = [c.status for c in checks if c.status != "skip"]
        if any(s == "fail" for s in statuses):
            page_mark = "FAIL"
        elif any(s == "warn" for s in statuses):
            page_mark = "WARN"
        elif statuses:
            page_mark = "PASS"
        else:
            page_mark = "SKIP"

        lines.append(f"## {page_mark} {path}")
        lines.append("")
        if pm.title:
            lines.append(f"**Title** ({len(pm.title)} chars): {pm.title}  ")
        if pm.meta is not None:
            lines.append(f"**Meta** ({len(pm.meta)} chars): {pm.meta}  ")
        else:
            lines.append("**Meta:** (none)  ")
        lines.append("")
        lines.append("| Status | Rule | Field | Reason |")
        lines.append("| --- | --- | --- | --- |")
        for c in checks:
            reason = c.reason.replace("|", "\\|")
            lines.append(f"| {c.status.upper()} | {c.rule} | {c.field} | {reason} |")
        lines.append("")

    lines += [
        "## Manual checks",
        "",
        "These cannot be fully automated. Review after the automated audit:",
        "",
        "- [ ] Each meta accurately describes the page's actual content and matches search intent.",
        "- [ ] Each meta contains one clear differentiator or next step, not just a keyword list.",
        "- [ ] No meta is a generic boilerplate that could apply to any page on the site.",
        "- [ ] Proposed metas read naturally — no awkward keyword insertion.",
        "",
        "## Next",
        "",
        "1. Fix FAILs, then review WARNs.",
        "2. Run proposed-meta check before applying: `aeo-audit metas " + site.slug + " --proposed FILE`",
        "3. After applying, re-run live: `aeo-audit metas " + site.slug + " --write`",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_meta_report(
    site: Site,
    results: list[tuple[PageMeta, list[RuleResult]]],
    warnings: list[str],
    proposed_file: str = "",
) -> Path:
    folder = data_root() / "reports" / site.slug
    folder.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    suffix = "-metas-proposed" if proposed_file else "-metas"
    path = folder / f"{today}{suffix}.md"
    path.write_text(markdown_meta_report(site, results, warnings, proposed_file))
    return path


def write_meta_json(
    site: Site,
    results: list[tuple[PageMeta, list[RuleResult]]],
    warnings: list[str],
    proposed_file: str = "",
) -> Path:
    folder = data_root() / "reports" / site.slug
    folder.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    suffix = "-metas-proposed" if proposed_file else "-metas"
    path = folder / f"{today}{suffix}.json"

    data = []
    for pm, checks in results:
        data.append({
            "url": pm.url,
            "path": _normalize_path(pm.url),
            "title": pm.title,
            "meta": pm.meta,
            "meta_chars": len(pm.meta) if pm.meta else None,
            "title_chars": len(pm.title) if pm.title else None,
            "og_title": pm.og_title,
            "og_description": pm.og_description,
            "h1s": pm.h1s,
            "in_sitemap": pm.in_sitemap,
            "robots_directives": pm.robots_directives,
            "checks": [
                {"rule": c.rule, "status": c.status, "field": c.field, "reason": c.reason}
                for c in checks
            ],
        })

    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return path
