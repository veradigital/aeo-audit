"""Extract JSON-LD, flag AEO schema gaps, print official validator URLs."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse

from aeo_audit.config import data_root, Site
from aeo_audit.http import CURL, Check, Fetch, abs_url, fetch, leak_hits

RICH_RESULTS = "https://search.google.com/test/rich-results?url="
SCHEMA_VALIDATOR = "https://validator.schema.org/#url="

ORG_TYPES = {
    "Organization",
    "ProfessionalService",
    "LocalBusiness",
    "AccountingService",
    "AutoRepair",
    "Church",
    "Dentist",
    "Electrician",
    "FoodEstablishment",
    "GeneralContractor",
    "HVACBusiness",
    "HairSalon",
    "HomeAndConstructionBusiness",
    "LegalService",
    "LiquorStore",
    "MedicalClinic",
    "Physician",
    "Plumber",
    "RealEstateAgent",
    "Restaurant",
    "RoofingContractor",
    "Store",
}
PRODUCT_TYPES = {"SoftwareApplication", "Product"}
ARTICLE_TYPES = {"Article", "BlogPosting", "NewsArticle", "TechArticle"}

ORG_NICE = ("telephone", "email", "address")


def validator_urls(page: str) -> tuple[str, str]:
    encoded = quote(page, safe=":/")
    return SCHEMA_VALIDATOR + encoded, RICH_RESULTS + encoded


def schema_org_validate(url: str) -> dict:
    """POST to the public Schema Markup Validator. Returns parsed totals + types."""
    with tempfile.TemporaryDirectory() as tmp:
        out = f"{tmp}/r"
        cmd = [
            CURL,
            "-sS",
            "-A",
            "AEO-Fleet/0.1",
            "-X",
            "POST",
            "https://validator.schema.org/validate",
            "-H",
            "Accept: application/json",
            "-H",
            "Content-Type: application/x-www-form-urlencoded",
            "--data-urlencode",
            f"url={url}",
            "--max-time",
            "40",
            "-o",
            out,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=False)
            raw = Path(out).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"error": str(exc), "types": [], "errors": -1, "warnings": -1}
    if raw.startswith(")]}'"):
        raw = raw[4:]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "validator JSON parse failed", "types": [], "errors": -1, "warnings": -1}
    if data.get("fetchError"):
        return {
            "error": str(data["fetchError"]),
            "types": [],
            "errors": int(data.get("totalNumErrors") or 0),
            "warnings": int(data.get("totalNumWarnings") or 0),
        }
    types: list[str] = []

    def walk(nodes) -> None:
        for node in nodes or []:
            for t in node.get("types") or []:
                val = t.get("value")
                if val and val not in types:
                    types.append(val)
            for prop in node.get("nodeProperties") or []:
                tgt = prop.get("target")
                if tgt:
                    walk([tgt])

    for group in data.get("tripleGroups") or []:
        walk(group.get("nodes"))
    return {
        "error": "",
        "types": types,
        "errors": int(data.get("totalNumErrors") or 0),
        "warnings": int(data.get("totalNumWarnings") or 0),
    }


def jsonld_blobs(html: str) -> list[str]:
    return re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def walk_nodes(node) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from walk_nodes(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    if "@graph" in node:
        yield from walk_nodes(node["@graph"])
    for key in ("about", "publisher", "mainEntity", "author", "isPartOf", "brand"):
        if key in node:
            yield from walk_nodes(node[key])


def parse_nodes(html: str) -> tuple[list[dict], bool]:
    nodes: list[dict] = []
    parse_fail = False
    for blob in jsonld_blobs(html):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            parse_fail = True
            continue
        nodes.extend(walk_nodes(data))
    return nodes, parse_fail


def node_types(node: dict) -> list[str]:
    raw = node.get("@type")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if raw:
        return [str(raw)]
    return []


def all_types(nodes: list[dict]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        out.extend(node_types(node))
    seen: list[str] = []
    for t in out:
        if t not in seen:
            seen.append(t)
    return seen


def collect_strings(value) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key in ("@id", "url", "name"):
            if isinstance(value.get(key), str):
                out.append(value[key])
        if isinstance(value.get("contentUrl"), str):
            out.append(value["contentUrl"])
    elif isinstance(value, list):
        for item in value:
            out.extend(collect_strings(item))
    return out


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().lstrip("www.")


def public_host(site: Site) -> str:
    return host_of(site.origin)


def id_urls(nodes: list[dict]) -> list[str]:
    found: list[str] = []
    for node in nodes:
        for key in ("@id", "url"):
            found.extend(collect_strings(node.get(key)))
        for key in ("author", "publisher", "logo", "image", "isPartOf"):
            found.extend(collect_strings(node.get(key)))
    return found


def org_nodes(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if set(node_types(n)) & ORG_TYPES]


def first_org(nodes: list[dict]) -> dict | None:
    orgs = org_nodes(nodes)
    return orgs[0] if orgs else None


def schema_pages(site: Site) -> list[tuple[str, str]]:
    """(role, path) — homepage, product/money, one article when listed."""
    pages: list[tuple[str, str]] = [("home", "/")]
    if site.product:
        product_path = next(
            (p for p in site.key_pages if p not in {"/", ""} and "blog" not in p and "about" not in p and "contact" not in p and "faq" not in p and "service" not in p),
            "",
        )
        # Prefer an explicit product-looking path
        for path in site.key_pages:
            low = path.lower()
            if any(tok in low for tok in ("inventory", "product", "app", "platform", "software")):
                product_path = path
                break
        if product_path:
            pages.append(("product", product_path))
    for path in site.key_pages:
        if "/blog/" in path and path.count("/") >= 3:
            pages.append(("article", path))
            break
    pages.append(("faq", "/faq/"))
    # de-dupe paths, keep first role
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for role, path in pages:
        if path in seen:
            continue
        seen.add(path)
        unique.append((role, path))
    return unique


def _org_checks(site: Site, nodes: list[dict], page_url: str) -> list[Check]:
    checks: list[Check] = []
    org = first_org(nodes)
    if not org:
        checks.append(
            Check(
                "schema-org",
                "fail",
                "Organization on this URL",
                f"No Organization. Types: {', '.join(all_types(nodes)) or 'none'}",
                "Answer engines resolve a company entity from Organization. WebPage alone is not enough.",
                "Add Organization (or ProfessionalService) on home/about with public url + @id.",
            )
        )
        return checks
    org_urls = collect_strings(org.get("url")) + collect_strings(org.get("@id"))
    public = public_host(site)
    bad_hosts = [u for u in org_urls if host_of(u) and host_of(u) != public]
    if bad_hosts:
        checks.append(
            Check(
                "schema-org-host",
                "fail",
                "Organization url / @id on public host",
                "; ".join(bad_hosts[:4]),
                "A Pantheon or staging @id splits the company into two entities. Google may keep Breadcrumbs and drop Organization.",
                "Set Live home/siteurl to the public origin, save Yoast on Live, regenerate the graph.",
            )
        )
    else:
        checks.append(
            Check(
                "schema-org-host",
                "pass",
                "Organization url / @id on public host",
                org_urls[0] if org_urls else "present",
            )
        )
    missing = [f for f in ORG_NICE if not org.get(f)]
    same_as = collect_strings(org.get("sameAs"))
    logo = org.get("logo")
    if missing:
        checks.append(
            Check(
                "schema-org-nap",
                "warn",
                "Organization contact fields",
                "Missing: " + ", ".join(missing),
                "telephone / email / address in schema should match the visible NAP.",
                "Add the same NAP that is already on Contact. Do not invent an address.",
            )
        )
    else:
        checks.append(
            Check("schema-org-nap", "pass", "Organization contact fields", "telephone, email, address present")
        )
    quality = (
        "linkedin.com",
        "sap.com",
        "youtube.com",
        "google.com/maps",
        "crunchbase.com",
        "facebook.com",
        "yelp.com",
        "instagram.com",
        "g.page",
        "maps.app.goo.gl",
        "business.google.com",
    )
    has_quality = any(any(q in s.lower() for q in quality) for s in same_as)
    if not same_as or not has_quality:
        checks.append(
            Check(
                "schema-org-sameas",
                "warn",
                "Organization sameAs",
                ", ".join(same_as) or "none",
                "sameAs is how engines attach LinkedIn / store listings to the public domain.",
                "Add real profiles already in use (LinkedIn, store, YouTube). Drop dead Facebook/X if unused.",
            )
        )
    else:
        checks.append(
            Check("schema-org-sameas", "pass", "Organization sameAs", f"{len(same_as)} profiles")
        )
    if not logo:
        checks.append(
            Check(
                "schema-org-logo",
                "warn",
                "Organization logo",
                "No logo",
                "Logo is a Google Organization / knowledge-panel signal.",
                "Point logo at the live mark on the public host.",
            )
        )
    else:
        checks.append(Check("schema-org-logo", "pass", "Organization logo", "present"))
    _ = page_url
    return checks


def _product_checks(site: Site, nodes: list[dict], role: str) -> list[Check]:
    if not site.product or role != "product":
        return []
    types = all_types(nodes)
    if any(t in PRODUCT_TYPES for t in types):
        return [
            Check(
                "schema-product",
                "pass",
                "SoftwareApplication / Product",
                ", ".join(t for t in types if t in PRODUCT_TYPES),
            )
        ]
    return [
        Check(
            "schema-product",
            "fail",
            "SoftwareApplication / Product",
            "Types: " + (", ".join(types) or "none"),
            "Organization without a product object lets engines know the company and still recommend someone else.",
            "Add SoftwareApplication for the flagship product. Name + url + description. "
            "Do not invent offers.price or aggregateRating. Point offers.url at the contact/demo page.",
        )
    ]


def _article_checks(site: Site, nodes: list[dict], role: str) -> list[Check]:
    if role != "article":
        return []
    types = all_types(nodes)
    public = public_host(site)
    if not any(t in ARTICLE_TYPES for t in types):
        return [
            Check(
                "schema-article",
                "fail",
                "Article / BlogPosting",
                "Types: " + (", ".join(types) or "none"),
                "Articles without Article schema are weaker citation targets.",
                "Emit Article or BlogPosting with headline, dates, image, author, publisher on the public host.",
            )
        ]
    bad: list[str] = []
    for node in nodes:
        if not (set(node_types(node)) & ARTICLE_TYPES):
            continue
        for key in ("author", "publisher"):
            for url in collect_strings(node.get(key)):
                if host_of(url) and host_of(url) != public:
                    bad.append(f"{key} {url}")
    if bad:
        return [
            Check(
                "schema-article-host",
                "fail",
                "Article author/publisher host",
                "; ".join(bad[:4]),
                "Author IDs on a staging host keep the byline off the public entity.",
                "Regenerate Yoast on Live so Person and Organization IDs use the public origin.",
            )
        ]
    return [Check("schema-article", "pass", "Article / BlogPosting", ", ".join(t for t in types if t in ARTICLE_TYPES))]


def _faq_checks(nodes: list[dict], page: Fetch, role: str) -> list[Check]:
    if role != "faq":
        return []
    if not (200 <= page.status < 400):
        return [
            Check(
                "schema-faq",
                "warn",
                "FAQPage",
                f"{page.status} /faq/",
                "A missing /faq/ URL is optional. Google AI Overviews do not require FAQPage. Buyer questions belong on the pages that already rank.",
                "Add the questions to an existing page. One FAQPage block is enough when those questions are visible.",
            )
        ]
    if "FAQPage" in all_types(nodes):
        return [Check("schema-faq", "pass", "FAQPage", f"{page.status} with FAQPage")]
    return [
        Check(
            "schema-faq",
            "warn",
            "FAQPage",
            f"{page.status} but no FAQPage schema",
            "Google does not require FAQPage for AI Overviews. Other answer engines quote a visible FAQ more reliably when the JSON-LD matches it.",
            "Add one FAQPage that matches the visible Q&A. Do not add a second FAQPage on the same URL.",
        )
    ]


def analyze_fetch(site: Site, role: str, page: Fetch) -> list[Check]:
    nodes, parse_fail = parse_nodes(page.body)
    checks: list[Check] = []
    types = all_types(nodes)
    if parse_fail:
        checks.append(
            Check(
                f"schema-parse:{role}",
                "fail",
                f"{role} JSON-LD parse",
                "A JSON-LD script failed to parse",
                "Broken schema is discarded by Google and by most engines.",
                "Fix the script, then re-run both official validators.",
            )
        )
    if 200 <= page.status < 400:
        checks.append(
            Check(
                f"schema-types:{role}",
                "pass" if types else "warn",
                f"{role} types",
                ", ".join(types) or "none",
            )
        )
    leaks = [u for u in id_urls(nodes) if leak_hits(u)]
    if 200 <= page.status < 400 and leaks:
        checks.append(
            Check(
                f"schema-leak:{role}",
                "fail",
                f"{role} host leaks",
                "; ".join(leaks[:6]),
                "Staging hosts in @id / url / author / publisher split the entity.",
                "Purge platform URLs from Yoast and regenerate on the public host.",
            )
        )
    elif 200 <= page.status < 400 and types:
        checks.append(Check(f"schema-leak:{role}", "pass", f"{role} host leaks", "No staging hosts in JSON-LD URLs"))
    if role == "home":
        checks.extend(_org_checks(site, nodes, page.final_url))
    checks.extend(_product_checks(site, nodes, role))
    checks.extend(_article_checks(site, nodes, role))
    checks.extend(_faq_checks(nodes, page, role))
    return checks


def review_site(site: Site) -> tuple[list[Check], list[tuple[str, str, Fetch]]]:
    fetched: list[tuple[str, str, Fetch]] = []
    checks: list[Check] = []
    for role, path in schema_pages(site):
        page = fetch(abs_url(site.origin, path))
        fetched.append((role, path, page))
        checks.extend(analyze_fetch(site, role, page))
        if 200 <= page.status < 400:
            official = schema_org_validate(page.final_url or abs_url(site.origin, path))
            if official.get("error"):
                checks.append(
                    Check(
                        f"schema-org-validator:{role}",
                        "warn",
                        f"{role} Schema Markup Validator",
                        official["error"],
                        "Official schema.org confirmation failed to run.",
                        "Open https://validator.schema.org/ on this URL and paste the result.",
                    )
                )
            elif official["errors"]:
                checks.append(
                    Check(
                        f"schema-org-validator:{role}",
                        "fail",
                        f"{role} Schema Markup Validator",
                        f"{official['errors']} errors / {official['warnings']} warnings. Types: "
                        + ", ".join(official["types"][:12]),
                        "Invalid schema.org is discarded.",
                        "Fix the JSON-LD, then re-run the validator.",
                    )
                )
            else:
                checks.append(
                    Check(
                        f"schema-org-validator:{role}",
                        "pass",
                        f"{role} Schema Markup Validator",
                        f"0 errors / {official['warnings']} warnings. Types: "
                        + ", ".join(official["types"][:12]),
                    )
                )
    return checks, fetched


def markdown_schema_report(
    site: Site,
    checks: list[Check],
    fetched: list[tuple[str, str, Fetch]],
    validator_notes: str = "",
) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Schema review — {site.display_name} — {today}",
        "",
        f"Site: {site.origin}  ",
        "Official confirmation: Schema Markup Validator + Google Rich Results Test. "
        "CLI extraction is not enough.",
        "",
        "## Pages + validator links",
        "",
        "| Role | URL | Schema.org | Rich Results |",
        "| --- | --- | --- | --- |",
    ]
    for role, path, page in fetched:
        url = page.final_url or abs_url(site.origin, path)
        schema_u, rich_u = validator_urls(url)
        lines.append(f"| {role} | {url} | [validate]({schema_u}) | [rich results]({rich_u}) |")
    lines += ["", "## Checks", "", "| Status | Check | Evidence |", "| --- | --- | --- |"]
    for check in checks:
        ev = check.evidence.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {check.status.upper()} | {check.title} | {ev} |")
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    if fails or warns:
        lines += ["", "## What to do", ""]
        for check in fails + warns:
            if not check.impact:
                continue
            lines += [
                f"### {check.title}",
                "",
                f"**Impact:** {check.impact}",
                "",
                f"**Do this:** {check.fix}",
                "",
            ]
    lines += [
        "",
        "## Official validator results",
        "",
        validator_notes.strip()
        or "_Agent: open both validator URLs for home, product, and one article. Paste detected types and error counts here._",
        "",
        "## After apply",
        "",
        "Re-run `aeo-audit schema "
        + site.slug
        + " --write` and re-open both tools. Do not call schema done on extraction only.",
        "",
    ]
    return "\n".join(lines)


def write_schema_report(
    site: Site,
    checks: list[Check],
    fetched: list[tuple[str, str, Fetch]],
    validator_notes: str = "",
) -> Path:
    folder = data_root() / "reports" / site.slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{date.today().isoformat()}-schema.md"
    path.write_text(markdown_schema_report(site, checks, fetched, validator_notes))
    return path


def print_schema_review(site: Site, checks: list[Check], fetched: list[tuple[str, str, Fetch]]) -> None:
    print(f"{site.display_name}  schema review")
    print()
    for role, path, page in fetched:
        url = page.final_url or abs_url(site.origin, path)
        schema_u, rich_u = validator_urls(url)
        print(f"{role:8}  {url}  ({page.status})")
        print(f"         schema.org     {schema_u}")
        print(f"         rich-results   {rich_u}")
        print()
    width = max((len(c.title) for c in checks), default=10)
    for check in checks:
        mark = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}[check.status]
        print(f"{mark:4}  {check.title:<{width}}  {check.evidence}")
