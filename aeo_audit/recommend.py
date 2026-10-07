"""Turn audit context into ordered fixes: titles, descriptions, content, schema.

Drafts use the site record and reports/<slug>/facts.md. They do not invent
claims, prices, or profile URLs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from aeo_audit.config import data_root, Site, short_brand
from aeo_audit.http import Check

_IMPACT = {"high": 0, "medium": 1, "low": 2}
_DIFFICULTY = {"easy": 0, "moderate": 1, "hard": 2}
_SMALL_WORDS = {"for", "and", "of", "the", "with", "to", "in"}


@dataclass
class Recommendation:
    impact: str
    difficulty: str
    kind: str
    target: str
    problem: str
    draft: str
    why: str


def sort_recommendations(recs: list[Recommendation]) -> list[Recommendation]:
    return sorted(recs, key=lambda r: (_IMPACT[r.impact], _DIFFICULTY[r.difficulty], r.target))


def load_facts(site: Site) -> dict[str, str]:
    path = data_root() / "reports" / site.slug / "facts.md"
    text = path.read_text() if path.is_file() else ""
    facts = {"text": text, "phone": "", "email": "", "address": "", "claims": ""}
    for line in text.splitlines():
        if "·" in line and "@" in line:
            parts = [p.strip(" -") for p in line.split("·")]
            if len(parts) >= 3:
                facts["address"] = parts[0].removeprefix("NAP:").strip(" -")
                facts["phone"] = parts[1]
                facts["email"] = parts[2]
        if "up to" in line.lower() and not facts["claims"]:
            facts["claims"] = line.lstrip("- ").strip()
    if not facts["phone"] and site.phone:
        facts["phone"] = site.phone
    return facts


def category_phrase(site: Site) -> str:
    raw = (site.vertical or site.product or site.name).split("/")[0].strip()
    words = []
    for i, word in enumerate(raw.split()):
        if word.isupper() or any(ch.isdigit() for ch in word):
            words.append(word)
        elif i and word.lower() in _SMALL_WORDS:
            words.append(word.lower())
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def product_name(site: Site) -> str:
    return (site.product or site.name).split("(")[0].strip()


def _fit(text: str, limit: int = 156) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;") + "."


def homepage_title(site: Site) -> str:
    return f"{category_phrase(site)} | {short_brand(site)}"


def _as_object(phrase: str) -> str:
    words = phrase.split()
    if words and not (words[0].isupper() and len(words[0]) <= 5):
        words[0] = words[0][:1].lower() + words[0][1:]
    return " ".join(words)


def homepage_description(site: Site, facts: dict[str, str]) -> str:
    product = product_name(site)
    category = _as_object(category_phrase(site))
    claim = ""
    if facts.get("claims"):
        percents = re.findall(r"up to \d+%(?:[^.;]*)", facts["claims"], flags=re.I)
        if percents:
            claim = percents[-1].strip().rstrip(".")
    sentence = f"{product} is {category}."
    if claim:
        sentence = _fit(f"{sentence.rstrip('. ')}. {claim[0].upper() + claim[1:].rstrip('.')}.")
    else:
        sentence = _fit(sentence)
    if len(sentence) < 120 and site.money_action:
        sentence = _fit(
            f"{sentence.rstrip('. ')}. Contact {short_brand(site)} to schedule a consultation."
        )
    return sentence


def llms_draft(site: Site, facts: dict[str, str]) -> str:
    lines = [
        f"# {site.name or short_brand(site)}",
        "",
        f"> {homepage_description(site, facts)}",
        "",
        "## Contact",
        f"- {site.money_action or site.origin + '/contact/'}",
    ]
    if facts.get("phone"):
        lines.append(f"- {facts['phone']}")
    if facts.get("email"):
        lines.append(f"- {facts['email']}")
    if facts.get("address"):
        lines.append(f"- {facts['address']}")
    lines += ["", "## Pages"]
    seen = set()
    for path in ["/", *site.key_pages]:
        if path in seen or "sapmobile" in path:
            continue
        seen.add(path)
        lines.append(f"- {site.origin}{path if path.startswith('/') else '/' + path}")
    lines += [
        "",
        "Use only the public host. Do not list staging hosts, pattern categories, or Uncategorized.",
    ]
    return "\n".join(lines)


def schema_nap_draft(facts: dict[str, str]) -> str:
    if not (facts.get("phone") and facts.get("email") and facts.get("address")):
        return ""
    address = facts["address"]
    street, locality, region, postal = address, "", "", ""
    match = re.search(r"(.+?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5})", address)
    if match:
        street, locality, region, postal = match.groups()
    block = {
        "@type": "Organization",
        "telephone": facts["phone"],
        "email": facts["email"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": street.strip(),
            "addressLocality": locality,
            "addressRegion": region,
            "postalCode": postal,
        },
    }
    return json.dumps(block, indent=2)


def build_recommendations(
    site: Site,
    audit_checks: list[Check],
    schema_checks: list[Check],
    facts: dict[str, str] | None = None,
    metas: list[dict] | None = None,
    ai_results: list[dict] | None = None,
    psi_results: list | None = None,
) -> list[Recommendation]:
    facts = facts if facts is not None else load_facts(site)
    by_id = {c.id: c for c in audit_checks}
    recs: list[Recommendation] = []

    title = by_id.get("title")
    if title and title.status == "fail":
        draft = homepage_title(site)
        recs.append(Recommendation(
            "high", "easy", "title", site.origin + "/",
            title.evidence,
            draft,
            "The homepage title is what Google and answer engines use to decide what the company sells. "
            f"End it with {short_brand(site)} so the phrase in front is the category, and the title stays inside 60 characters ({len(draft)}).",
        ))

    meta = by_id.get("meta")
    if meta and meta.status in {"fail", "warn"}:
        draft = homepage_description(site, facts)
        recs.append(Recommendation(
            "high", "easy", "description", site.origin + "/",
            meta.evidence,
            draft,
            f"Description length is {len(draft)} characters. The useful range is 120–156. "
            "It names the product and only uses a claim already in the fact lock.",
        ))

    h1 = by_id.get("h1")
    if h1 and h1.status in {"fail", "warn"}:
        recs.append(Recommendation(
            "medium", "moderate", "content", site.origin + "/",
            h1.evidence,
            "Keep one H1 that names the category. Where a slide states 30% or 50%, write \"up to\" in front of it, matching the fact lock.",
            "Three H1s compete, and a bare percentage is a stronger claim than the site's own \"up to\" wording.",
        ))

    llms = by_id.get("llms-quality")
    if llms and llms.status == "fail":
        recs.append(Recommendation(
            "high", "moderate", "content", site.origin + "/llms.txt",
            llms.evidence,
            llms_draft(site, facts),
            "ChatGPT, Claude, and Perplexity may read this file. Google does not. "
            "The live file still points at a staging host and never names the product.",
        ))

    for check in audit_checks:
        if check.id.endswith(":index") and "noindex" in check.evidence.lower():
            recs.append(Recommendation(
                "low", "easy", "decision", check.title.replace("Index and snippet eligible ", ""),
                check.evidence,
                "Leave the noindex in place if that URL is intentional. Remove the path from key_pages so the audit stops treating it as a public page.",
                "noindex keeps the URL out of Google. Removing it would publish a page that was blocked on purpose.",
            ))

    faq = by_id.get("faq")
    if faq and faq.status in {"fail", "warn"} and "404" in faq.evidence:
        recs.append(Recommendation(
            "low", "easy", "schema", site.origin + "/faq/",
            faq.evidence,
            "Do not create a sitewide /faq/ page to satisfy this check. Keep the FAQ schema on the articles that already show the questions.",
            "A second FAQ page would duplicate answers. Google no longer shows an FAQ dropdown.",
        ))

    for check in schema_checks:
        if check.id == "schema-org-nap" and check.status in {"fail", "warn"}:
            draft = schema_nap_draft(facts)
            recs.append(Recommendation(
                "high", "easy", "schema", site.origin + "/",
                check.evidence,
                draft or "Add telephone, email, and address from the contact page. Do not invent a NAP.",
                "Organization schema is valid, and it is missing the contact fields engines use to match the company.",
            ))
        if check.id == "schema-org-sameas" and check.status in {"fail", "warn"}:
            recs.append(Recommendation(
                "medium", "easy", "schema", site.origin + "/",
                check.evidence,
                "Add sameAs URLs that are already public (LinkedIn, the product store listing). Do not invent a profile URL.",
                "sameAs ties the public domain to the profiles an answer engine already trusts.",
            ))

    recs.extend(_meta_recs(site, metas or []))
    recs.extend(_ai_recs(site, facts, ai_results or []))
    recs.extend(_psi_recs(psi_results or []))
    return sort_recommendations(recs)


def _legal_description(site: Site, path: str) -> str:
    """A description of a privacy or terms page, not a product pitch."""
    slug = path.strip("/").lower()
    name = site.name or short_brand(site)
    if slug in {"privacy-policy", "privacy"}:
        return _fit(
            f"This privacy policy explains how {name} collects, uses, and protects "
            "information you submit on this website."
        )
    if slug in {"terms-of-service", "terms", "terms-and-conditions", "terms-of-use"}:
        return _fit(
            f"These terms of service govern your use of this website and services "
            f"from {name}. Using the site means you agree to them."
        )
    return ""


def _meta_recs(site: Site, metas: list[dict]) -> list[Recommendation]:
    if not metas:
        return []
    brand = short_brand(site)
    blog_long: list[str] = []
    missing: list[dict] = []
    recs: list[Recommendation] = []
    for page in metas:
        path = page.get("path") or "/"
        if not path.endswith("/"):
            path += "/"
        checks = {c.get("rule"): c for c in page.get("checks") or []}
        title = page.get("title") or ""
        if path in {"/", ""}:
            continue
        if checks.get("title-length", {}).get("status") == "fail" and path.startswith("/blog/"):
            blog_long.append(title)
        meta_missing = checks.get("meta-missing", {}).get("status") == "fail"
        if meta_missing and not path.startswith("/blog/"):
            missing.append(page)
    if blog_long:
        examples = []
        for title in blog_long[:3]:
            front = title.split("|")[0].strip()
            examples.append(f"{front} | {brand}")
        recs.append(Recommendation(
            "medium", "moderate", "title", "blog posts",
            f"{len(blog_long)} blog titles are over 70 characters and will be cut off.",
            "\n".join(examples),
            f"Swap the long company name for {brand}. If the headline itself is still over 60 characters, shorten the front half. Do not change the article body.",
        ))
    key = set(site.key_pages)
    missing.sort(key=lambda p: (0 if (p.get("path") or "") in key else 1, p.get("path") or ""))
    for page in missing[:6]:
        path = page.get("path") or "/"
        front = (page.get("title") or path).split("|")[0].strip()
        legal = _legal_description(site, path)
        if legal:
            draft = legal
            why = (
                f"Draft is {len(draft)} characters and describes this legal page. "
                "It does not pitch the product."
            )
        else:
            draft = _fit(f"{front}. {product_name(site)} helps with {_as_object(category_phrase(site))}.")
            why = (
                f"Draft is {len(draft)} characters and starts with the page title. "
                "Replace it if the page's opening line is more specific. "
                "Do not paste the whole opening paragraph."
            )
        recs.append(Recommendation(
            "medium", "easy", "description", site.origin + path,
            "No meta description tag.",
            draft,
            why,
        ))
    return recs


def _ai_recs(site: Site, facts: dict[str, str], results: list[dict]) -> list[Recommendation]:
    missed = [r for r in results if not r.get("error") and not r.get("mentioned")]
    if not missed:
        return []
    prompts = "\n".join(f"- {r.get('prompt')}" for r in missed)
    claim = ""
    if facts.get("claims"):
        bits = re.findall(r"up to \d+%[^.;]*", facts["claims"], flags=re.I)
        claim = "; ".join(bit.strip() for bit in bits)
    paragraph = _fit(
        f"{product_name(site)} is {_as_object(category_phrase(site))}. {claim}".strip(),
        400,
    )
    return [Recommendation(
        "high", "hard", "content", site.origin + "/",
        f"Gemini with Google Search did not name the company on {len(missed)} category question(s).",
        prompts + "\n\nAnswer-first paragraph to add on the homepage:\n" + paragraph,
        "Questions that already contain the company name get a citation. Questions about the category do not. "
        "A public answer that uses the category words is the content those answers can cite.",
    )]


def _psi_recs(results: list) -> list[Recommendation]:
    weak = [r for r in results if not getattr(r, "error", "") and getattr(r, "strategy", "") == "mobile" and getattr(r, "performance", 100) < 50]
    if not weak:
        return []
    worst = min(weak, key=lambda r: r.performance)
    from urllib.parse import urlparse
    path = urlparse(worst.url).path or "/"
    return [Recommendation(
        "medium", "hard", "speed", worst.url,
        f"Mobile performance {worst.performance:.0f} on {path}. LCP {worst.lcp:.0f}ms.",
        "Compress the largest homepage image and remove scripts that are not needed for the first view. Re-run PageSpeed after that.",
        "Speed is a ranking and usability issue. It does not fix a title that describes the wrong offer, so it comes after the snippet work.",
    )]


def format_recommendations(site: Site, recs: list[Recommendation]) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Recommendations — {site.display_name} — {today}",
        "",
        f"Site: {site.origin}",
        "",
        "Ordered by impact, then by how hard the change is. High and easy first.",
        "Drafts use the site record and the fact lock. They do not add claims that are not already approved.",
        "",
        "| Order | Impact | Difficulty | Kind | Target |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, rec in enumerate(recs, start=1):
        lines.append(
            f"| {i} | {rec.impact} | {rec.difficulty} | {rec.kind} | {rec.target.replace('|', '/')} |"
        )
    lines.append("")
    for i, rec in enumerate(recs, start=1):
        lines += [
            f"## {i}. {rec.kind}: {rec.target}",
            "",
            f"**Impact:** {rec.impact}  ",
            f"**Difficulty:** {rec.difficulty}",
            "",
            rec.problem,
            "",
            "**Draft**",
            "",
            rec.draft,
            "",
            rec.why,
            "",
        ]
    return "\n".join(lines) + "\n"


def write_recommendations(site: Site, recs: list[Recommendation]) -> Path:
    folder = data_root() / "reports" / site.slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{date.today().isoformat()}-recommendations.md"
    path.write_text(format_recommendations(site, recs))
    return path


def latest_json(site: Site, suffix: str) -> list | None:
    folder = data_root() / "reports" / site.slug
    if not folder.is_dir():
        return None
    files = sorted(
        (path for path in folder.glob(f"*-{suffix}.json") if path.name[:4].isdigit()),
        reverse=True,
    )
    if not files:
        return None
    try:
        data = json.loads(files[0].read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def run_recommend(site: Site, with_psi: bool = True) -> tuple[list[Recommendation], str]:
    """Live gather. PSI runs only when a key is set and with_psi is true."""
    from aeo_audit.audit import audit_site
    from aeo_audit.config import env_key
    from aeo_audit.schema import review_site

    audit_checks = audit_site(site)
    schema_checks, _ = review_site(site)
    facts = load_facts(site)
    metas = latest_json(site, "metas") or []
    ai_results = latest_json(site, "ai-check") or []
    psi_results = []
    notes = []
    if with_psi and env_key("PSI_API_KEY"):
        try:
            from aeo_fleet.psi import psi_checks
        except ImportError:
            psi_checks = None
            notes.append("PageSpeed is not part of this install.")
        if psi_checks is not None:
            psi_results, _ = psi_checks(site)
            notes.append("PageSpeed ran for the first three key pages, mobile and desktop.")
    elif with_psi:
        notes.append("PageSpeed key is not set.")
    if not ai_results:
        notes.append("No saved AI answer check.")
    recs = build_recommendations(
        site, audit_checks, schema_checks, facts, metas, ai_results, psi_results,
    )
    return recs, " ".join(notes)
