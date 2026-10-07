from __future__ import annotations

import re
from urllib.parse import urlparse

from aeo_audit.config import Site
from aeo_audit.http import (
    Check,
    Fetch,
    abs_url,
    all_tags,
    fetch,
    first_tag,
    jsonld_types,
    leak_hits,
)
from aeo_audit.schema import ORG_TYPES

PRODUCT_SCHEMA = ("SoftwareApplication", "Product", "FAQPage")

# Crawlers that fetch pages for live answers. A sitewide block hides the brand there.
SEARCH_BOTS = (
    "OAI-SearchBot",
    "ChatGPT-User",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
    "Perplexity-User",
)

# Training opt-out. Blocking these does not remove Google AI Overviews.
TRAINING_BOTS = (
    "GPTBot",
    "ClaudeBot",
    "Google-Extended",
    "Applebot-Extended",
    "CCBot",
)


def _ok(status: int) -> bool:
    return 200 <= status < 400


def audit_site(site: Site) -> list[Check]:
    checks: list[Check] = []
    origin = site.origin
    home = fetch(origin + "/")
    robots = fetch(abs_url(origin, "/robots.txt"))
    llms = fetch(abs_url(origin, "/llms.txt"))
    sitemap_url = _sitemap_from_robots(robots) or abs_url(origin, "/sitemap_index.xml")
    sitemap = fetch(sitemap_url)
    faq = fetch(abs_url(origin, "/faq/"))

    checks.append(_home_check(site, home))
    checks.append(_title_check(site, home))
    checks.append(_meta_check(site, home))
    checks.append(_h1_check(home))
    checks.append(_robots_check(robots))
    checks.append(_ai_bots_check(robots))
    checks.append(_snippet_check(home))
    checks.append(_sitemap_check(sitemap, sitemap_url))
    checks.append(_llms_exists_check(llms))
    checks.append(_llms_quality_check(site, llms))
    checks.append(_faq_check(faq))
    checks.append(_schema_check(site, home))
    checks.append(_leak_check("home-html", "Homepage HTML host leaks", home.body))
    checks.append(_leak_check("llms-hosts", "llms.txt host leaks", llms.body))
    checks.append(_leak_check("schema-hosts", "JSON-LD host leaks", home.body))
    checks.extend(_key_page_checks(site))
    return checks


def _home_check(site: Site, home: Fetch) -> Check:
    host = urlparse(site.url).netloc
    final_host = urlparse(home.final_url).netloc
    if not _ok(home.status):
        return Check(
            "home",
            "fail",
            "Homepage reachable",
            f"{home.status} {home.final_url}",
            "If the homepage is down or blocked, every answer engine fails closed.",
            "Fix hosting/DNS/bot blocking, then re-audit.",
        )
    if host and final_host and host.lstrip("www.") != final_host.lstrip("www."):
        return Check(
            "home",
            "warn",
            "Homepage reachable",
            f"{home.status} → {home.final_url}",
            "A host mismatch splits entity confidence.",
            "301 the unused host to the canonical origin.",
        )
    return Check("home", "pass", "Homepage reachable", f"{home.status} {home.final_url}")


def _title_check(site: Site, home: Fetch) -> Check:
    title = first_tag(home.body, r"<title[^>]*>(.*?)</title>")
    if not title:
        return Check(
            "title",
            "fail",
            "Homepage title",
            "No <title>",
            "Answer engines often take the title as the entity label.",
            "Write a title that names the product + category, not a services laundry list.",
        )
    product = (site.product.split("(")[0] if site.product else "").strip()
    name_bits = {b.lower() for b in site.name.split() if len(b) > 2}
    distinctive = [
        b.lower()
        for b in product.replace("-", " ").split()
        if len(b) > 3 and b.lower() not in name_bits
    ]
    mentions = (not distinctive) or any(bit in title.lower() for bit in distinctive)
    if site.product and not mentions:
        return Check(
            "title",
            "fail",
            "Homepage title names the offer",
            title,
            "The visible homepage can be product-led while the title still teaches AI the old services story.",
            f"Retitle around {site.product or site.name} and the category a buyer would type.",
        )
    return Check("title", "pass", "Homepage title names the offer", title)


def _meta_check(site: Site, home: Fetch) -> Check:
    tag = first_tag(
        home.body,
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    )
    if not tag:
        tag = first_tag(
            home.body,
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        )
    if not tag:
        return Check(
            "meta",
            "fail",
            "Meta description",
            "Missing",
            "Thin or missing descriptions make the page harder to quote.",
            "Add a 1–2 sentence description that states who it is for and what it does.",
        )
    product = (site.product or site.name).split("(")[0].strip()
    if product and product.lower() not in tag.lower():
        return Check(
            "meta",
            "fail",
            "Meta description matches the offer",
            tag,
            "Crawlers will summarize the services tagline even when the page body is about the product.",
            "Rewrite the Yoast/meta description to the current offer. Keep it factual.",
        )
    return Check("meta", "pass", "Meta description matches the offer", tag)


def _h1_check(home: Fetch) -> Check:
    h1s = [h for h in all_tags(home.body, r"<h1[^>]*>(.*?)</h1>") if h]
    if not h1s:
        return Check(
            "h1",
            "fail",
            "Single clear H1",
            "No H1",
            "Answer engines look for one primary statement.",
            "One H1 that states the outcome + category.",
        )
    if len(h1s) > 1:
        return Check(
            "h1",
            "warn",
            "Single clear H1",
            f"{len(h1s)} H1s: " + " | ".join(h1s[:4]),
            "Hero sliders with a new H1 per slide dilute the quotable statement.",
            "One H1. Slide copy can be H2/p.",
        )
    return Check("h1", "pass", "Single clear H1", h1s[0])


def _robots_check(robots: Fetch) -> Check:
    if not _ok(robots.status) or not robots.body.strip():
        return Check(
            "robots",
            "fail",
            "robots.txt",
            f"{robots.status}",
            "Missing robots hides the sitemap and looks unfinished to crawlers.",
            "Publish robots.txt with a Sitemap: line and no blanket AI blocks.",
        )
    if "sitemap:" not in robots.body.lower():
        return Check(
            "robots",
            "warn",
            "robots.txt lists a sitemap",
            "No Sitemap: line",
            "Some crawlers only discover URLs through robots.",
            "Add Sitemap: https://example.com/sitemap.xml",
        )
    return Check("robots", "pass", "robots.txt", f"{robots.status}, sitemap declared")


def robots_groups(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """User-agent lines share a group until the next rule block."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal agents, rules
        if agents or rules:
            groups.append((agents, rules))
        agents, rules = [], []

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            flush()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if rules:
                flush()
            agents.append(value)
        elif key in {"allow", "disallow"}:
            rules.append((key, value))
    flush()
    return groups


def group_blocks_site(rules: list[tuple[str, str]]) -> bool:
    blocked = False
    for key, value in rules:
        if key == "disallow" and value == "/":
            blocked = True
        elif key == "allow" and value == "/":
            blocked = False
    return blocked


def winning_group(
    groups: list[tuple[list[str], list[tuple[str, str]]]], bot: str
) -> tuple[list[str], list[tuple[str, str]]] | None:
    specific = []
    star = []
    for agents, rules in groups:
        lows = [agent.lower() for agent in agents]
        if bot.lower() in lows:
            specific.append((agents, rules))
        if "*" in lows:
            star.append((agents, rules))
    if bot == "*":
        return star[0] if star else None
    if specific:
        return specific[0]
    return star[0] if star else None


def bots_blocked(text: str, names: tuple[str, ...]) -> list[str]:
    groups = robots_groups(text)
    blocked = []
    for name in names:
        group = winning_group(groups, name)
        if group and group_blocks_site(group[1]):
            blocked.append(name)
    return blocked


def _ai_bots_check(robots: Fetch) -> Check:
    if not _ok(robots.status):
        return Check("ai-bots", "skip", "Answer crawlers allowed", "No robots.txt")
    search_blocked = bots_blocked(robots.body, SEARCH_BOTS)
    training_blocked = bots_blocked(robots.body, TRAINING_BOTS)
    if search_blocked:
        return Check(
            "ai-bots",
            "fail",
            "Answer crawlers allowed",
            "Blocked: " + ", ".join(search_blocked),
            "These crawlers fetch pages for ChatGPT, Claude, or Perplexity answers. A sitewide Disallow hides the brand in that engine. User-agent: * with Disallow: / blocks them too.",
            "Remove the block unless compliance requires it. A block on GPTBot, ClaudeBot, or Google-Extended only limits training. It does not remove the site from Google AI Overviews.",
        )
    if training_blocked:
        return Check(
            "ai-bots",
            "warn",
            "Training crawlers",
            "Blocked: " + ", ".join(training_blocked),
            "GPTBot, ClaudeBot, and Google-Extended limit model training. They do not control Google AI Overviews or whether ChatGPT can fetch the page.",
            "Leave the block if the training opt-out is intentional.",
        )
    return Check("ai-bots", "pass", "Answer crawlers allowed", "Search crawlers are not blocked")


def _sitemap_check(sitemap: Fetch, url: str) -> Check:
    if sitemap.status == 500:
        return Check(
            "sitemap",
            "fail",
            "Sitemap reachable",
            f"500 at {url}",
            "Some AI/user-agent fetches get a 500 even when browsers get 200. Those crawlers never see the URL list.",
            "Serve the sitemap to all user-agents. Do not WAF-block unknown bots on /sitemap*.xml.",
        )
    if not _ok(sitemap.status):
        return Check(
            "sitemap",
            "fail",
            "Sitemap reachable",
            f"{sitemap.status} {url}",
            "No sitemap = weak discovery.",
            "Fix or generate the XML sitemap.",
        )
    if "<url" not in sitemap.body and "<sitemap" not in sitemap.body:
        return Check(
            "sitemap",
            "warn",
            "Sitemap looks like XML",
            f"{sitemap.status} but no <url>/<sitemap> nodes",
            "An HTML error page at the sitemap URL is as bad as a 404.",
            "Return real XML.",
        )
    return Check("sitemap", "pass", "Sitemap reachable", f"{sitemap.status} {url}")


def _directive_hits(value: str) -> list[str]:
    hits = []
    for token in value.lower().split(","):
        token = token.strip().replace(" ", "")
        if token in {"noindex", "none", "nosnippet"} or token == "max-snippet:0":
            hits.append(token)
    return hits


def snippet_block_reasons(headers: dict[str, str], html: str) -> list[str]:
    """noindex, none, nosnippet, and max-snippet:0. These block Google Search and AI Overviews."""
    reasons: list[str] = []
    xrobots = headers.get("x-robots-tag", "")
    if xrobots and _directive_hits(xrobots):
        reasons.append("X-Robots-Tag: " + xrobots)
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.I):
        name_match = re.search(r"""\bname\s*=\s*['"]([^'"]+)['"]""", tag, flags=re.I)
        content_match = re.search(r"""\bcontent\s*=\s*['"]([^'"]+)['"]""", tag, flags=re.I)
        if not name_match or not content_match:
            continue
        name = name_match.group(1).lower()
        if name not in {"robots", "googlebot"}:
            continue
        content = content_match.group(1)
        if _directive_hits(content):
            reasons.append(f"meta {name}: {content}")
    return reasons


def _snippet_check(home: Fetch) -> Check:
    if not _ok(home.status):
        return Check("snippet", "skip", "Index and snippet eligible", "Homepage not readable")
    reasons = snippet_block_reasons(home.headers, home.body)
    if reasons:
        return Check(
            "snippet",
            "fail",
            "Index and snippet eligible",
            "; ".join(reasons),
            "noindex and none keep the page out of Google. nosnippet and max-snippet:0 block AI Overviews and AI Mode, and they also remove the normal Google snippet.",
            "Remove noindex, none, nosnippet, and max-snippet:0 on public pages. Inclusion in AI Overviews is Search Console → Settings → Search generative AI, set to include.",
        )
    return Check("snippet", "pass", "Index and snippet eligible", "No noindex, nosnippet, or max-snippet:0")


def _llms_exists_check(llms: Fetch) -> Check:
    if not _ok(llms.status) or len(llms.body.strip()) < 40:
        return Check(
            "llms-exists",
            "warn",
            "/llms.txt exists",
            f"{llms.status}, {len(llms.body)} bytes",
            "ChatGPT, Perplexity, and Claude may read /llms.txt. Google Search, including AI Overviews and AI Mode, ignores it. A missing file is a gap for those three engines, not a Google failure.",
            "Publish a hand-authored llms.txt for the non-Google engines. Do not ship a raw Yoast dump. Do not treat the file as a Google ranking file.",
        )
    return Check("llms-exists", "pass", "/llms.txt exists", f"{llms.status}, {len(llms.body)} bytes")


def _llms_quality_check(site: Site, llms: Fetch) -> Check:
    if not _ok(llms.status):
        return Check("llms-quality", "skip", "llms.txt quality", "File missing")
    body = llms.body
    problems = []
    if body.count("# ") >= 4 and body.count(site.name.split()[0] if site.name else "http") >= 2:
        # duplicated file concatenated
        if body.count("Generated by Yoast") > 1 or body.count("## Pages") > 1:
            problems.append("file is concatenated twice")
    leaks = leak_hits(body)
    if leaks:
        problems.append("non-canonical hosts: " + ", ".join(leaks))
    low = body.lower()
    if "block_pattern_category" in low or "/blog/category/uncategorized" in low:
        problems.append("includes WP junk (patterns, Uncategorized)")
    if site.money_action and site.money_action.rstrip("/") not in body:
        problems.append("missing money-action URL")
    if site.product and site.product.split("(")[0].strip().lower() not in low:
        problems.append("does not name the product")
    needed = ("faq", "contact", "hours", "phone", "email")
    missing_bits = [w for w in needed if w not in low]
    if len(missing_bits) >= 3:
        problems.append("thin facts (no FAQ/NAP-style block)")
    if problems:
        return Check(
            "llms-quality",
            "fail",
            "llms.txt is a useful brief",
            "; ".join(problems),
            "Engines that read /llms.txt learn the staging host or a services-era tagline. Google Search does not read this file.",
            "Replace with a hand-authored brief: who, product, facts, FAQ, money URL, production page list. On Pantheon+Yoast, do not serve a Dev-generated file.",
        )
    return Check("llms-quality", "pass", "llms.txt is a useful brief", "Facts + production hosts")


def _faq_check(faq: Fetch) -> Check:
    if faq.status == 404:
        return Check(
            "faq",
            "warn",
            "FAQ URL exists",
            "404 /faq/",
            "A dedicated /faq/ URL is optional. Buyer questions belong on the pages that already rank. Google AI Overviews do not require FAQPage.",
            "Add the questions to the existing page. One FAQPage JSON-LD block is enough when the questions are visible. Do not create a new URL for every related query.",
        )
    if not _ok(faq.status):
        return Check(
            "faq",
            "warn",
            "FAQ URL exists",
            f"{faq.status} /faq/",
            "If FAQ lives elsewhere, say so in inventory and put FAQPage schema on that URL only.",
            "Pick one canonical FAQ URL. Do not duplicate FAQ schema on Contact.",
        )
    types = jsonld_types(faq.body)
    if "FAQPage" not in types:
        return Check(
            "faq",
            "warn",
            "FAQPage JSON-LD",
            f"{faq.status} but no FAQPage schema",
            "Google dropped FAQ rich results in May 2026 and does not require FAQPage for AI Overviews. Other answer engines still quote a visible FAQ more reliably when the JSON-LD matches.",
            "Add one FAQPage JSON-LD block that matches the visible answers. Do not add a second FAQPage on the same URL.",
        )
    return Check("faq", "pass", "FAQ URL + FAQPage schema", f"{faq.status} /faq/")


def _schema_check(site: Site, home: Fetch) -> Check:
    types = jsonld_types(home.body)
    if "PARSE_FAIL" in types:
        return Check(
            "schema",
            "fail",
            "Useful JSON-LD",
            "JSON-LD failed to parse",
            "Broken schema is discarded.",
            "Validate JSON-LD and re-publish.",
        )
    useful = [t for t in types if t in ORG_TYPES or t in PRODUCT_SCHEMA]
    if not useful:
        return Check(
            "schema",
            "fail",
            "Useful JSON-LD",
            "Types: " + (", ".join(types) or "none"),
            "WebPage + WebSite + BreadcrumbList is Yoast default. It does not teach the product, offer, or org.",
            "Add Organization or a real LocalBusiness subtype, plus SoftwareApplication/Product when there is a product. Never invent aggregateRating or a price.",
        )
    if site.product and not any(t in types for t in ("SoftwareApplication", "Product")):
        return Check(
            "schema",
            "warn",
            "Product schema",
            "Organization present; no SoftwareApplication/Product. Types: "
            + ", ".join(sorted(set(types))),
            "Engines can resolve the company and still miss the product they should recommend.",
            "Add SoftwareApplication (or Product) for the flagship offer, linked from Organization.",
        )
    return Check("schema", "pass", "Useful JSON-LD", ", ".join(sorted(set(types))))


def _leak_check(cid: str, title: str, text: str) -> Check:
    hits = leak_hits(text)
    if not hits:
        return Check(cid, "pass", title, "No staging/dev hosts")
    return Check(
        cid,
        "fail",
        title,
        ", ".join(hits),
        "Entity confidence splits across the public domain and the host platform URL. AI may cite the wrong host or refuse to recommend.",
        "Force canonical host in WP home/siteurl, Yoast, and any generated files. Regenerate llms.txt and schema on production.",
    )


def _key_page_checks(site: Site) -> list[Check]:
    out: list[Check] = []
    for path in site.key_pages:
        if path in {"/", ""}:
            continue
        page = fetch(abs_url(site.origin, path))
        cid = "page:" + path
        if not _ok(page.status):
            out.append(
                Check(
                    cid,
                    "fail",
                    f"Key page {path}",
                    f"{page.status}",
                    "Broken money/content URLs drop citation surface.",
                    "Restore or redirect.",
                )
            )
        else:
            out.append(Check(cid, "pass", f"Key page {path}", f"{page.status}"))
            reasons = snippet_block_reasons(page.headers, page.body)
            if reasons:
                out.append(
                    Check(
                        cid + ":index",
                        "fail",
                        f"Index and snippet eligible {path}",
                        "; ".join(reasons),
                        "noindex keeps the URL out of Google. nosnippet and max-snippet:0 block AI Overviews and the normal snippet.",
                        "Remove noindex, none, nosnippet, and max-snippet:0 on this public page.",
                    )
                )
    return out


def _sitemap_from_robots(robots: Fetch) -> str | None:
    if not _ok(robots.status):
        return None
    for line in robots.body.splitlines():
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    return None


def score(checks: list[Check]) -> tuple[int, int, int]:
    fail = sum(1 for c in checks if c.status == "fail")
    warn = sum(1 for c in checks if c.status == "warn")
    passed = sum(1 for c in checks if c.status == "pass")
    return passed, warn, fail
