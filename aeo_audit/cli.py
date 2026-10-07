"""CLI for the public checker: audit, crawl, metas, schema, content, consistency."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from aeo_audit import __version__
from aeo_audit.audit import audit_site
from aeo_audit.config import (
    FleetError,
    bundled_example,
    data_root,
    load_sites,
    resolve_site_or_domain,
)
from aeo_audit.meta import (
    audit_site_metas,
    print_meta_table,
    write_meta_json,
    write_meta_report,
)
from aeo_audit.report import print_table, write_report
from aeo_audit.schema import print_schema_review, review_site, write_schema_report


def _fail(message: str, code: int = 1) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _resolve(args: argparse.Namespace):
    entity = getattr(args, "entity", "") or ""
    return resolve_site_or_domain(args.site, entity=entity)


def cmd_init(_args: argparse.Namespace) -> int:
    root = data_root()
    dest = root / "inventory" / "sites.toml"
    src = bundled_example()
    if dest.exists():
        print(f"Already exists: {dest.relative_to(root)}")
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    print(f"Created {dest.relative_to(root)}. Add a site, then: aeo-audit list")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    try:
        sites = load_sites()
    except FleetError as exc:
        return _fail(str(exc))
    if not sites:
        print("No sites. Run: aeo-audit init")
        return 0
    width = max(len(s.slug) for s in sites.values())
    for site in sites.values():
        print(f"{site.slug:<{width}}  {site.stack:<12}  {site.origin}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))
    checks = audit_site(site)
    print_table(site, checks)
    if args.write:
        path = write_report(site, checks)
        print()
        print(f"Wrote {path}")
    return 0 if all(c.status != "fail" for c in checks) else 2


def cmd_crawl(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))

    from aeo_audit.crawl import crawl_site

    cap = args.pages or 50
    print(f"Crawling {site.origin} (cap {cap} pages)...")
    pages, checks = crawl_site(site, page_cap=cap, politeness=args.delay)
    print(f"Crawled {len(pages)} pages.")
    print()
    print_table(site, checks)
    if args.write:
        path = write_report(site, checks, extra=f"Crawled {len(pages)} pages.", kind="crawl")
        print()
        print(f"Wrote {path}")
    return 0 if all(c.status != "fail" for c in checks) else 2


def cmd_schema(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))
    checks, fetched = review_site(site)
    print_schema_review(site, checks, fetched)
    if args.write:
        path = write_schema_report(site, checks, fetched)
        print()
        print(f"Wrote {path}")
        print("Open the schema.org and Rich Results URLs above. Paste detected types into the report.")
    return 0 if all(c.status != "fail" for c in checks) else 2


def cmd_metas(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))
    proposed = Path(args.proposed) if args.proposed else None
    if proposed and not proposed.exists():
        return _fail(f"File not found: {proposed}")
    results, warnings = audit_site_metas(site, proposed_file=proposed)
    print_meta_table(site, results, warnings)
    if args.write:
        md_path = write_meta_report(
            site, results, warnings, proposed_file=str(proposed) if proposed else ""
        )
        json_path = write_meta_json(
            site, results, warnings, proposed_file=str(proposed) if proposed else ""
        )
        print()
        print(f"Wrote {md_path}")
        print(f"Wrote {json_path}")
    has_fail = any(c.status == "fail" for _, checks in results for c in checks)
    return 2 if has_fail else 0


def cmd_prompts(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))
    if not site.prompts:
        print("No prompts in inventory. Add prompts = [ ... ] for this site.")
        return 0
    print(f"# Buyer prompts — {site.display_name}")
    print("Run verbatim in ChatGPT, Claude, Gemini, Perplexity. Record mention / citation / accuracy.")
    print()
    for i, prompt in enumerate(site.prompts, 1):
        print(f"{i}. {prompt}")
    return 0


def cmd_keyphrase(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))

    from urllib.parse import urlparse

    from aeo_audit.crawl import crawl_site
    from aeo_audit.keyphrase import (
        check_cannibalization,
        check_keyphrase_placement,
        keyphrase_for_page,
    )

    cap = args.pages or 20
    print(f"Crawling {site.origin} for keyphrase analysis (cap {cap})...")
    pages, _ = crawl_site(site, page_cap=cap, politeness=0.5)
    all_checks = []
    for page in pages:
        if page.status >= 400:
            continue
        path = urlparse(page.url).path
        kp = keyphrase_for_page(site, path)
        all_checks.extend(check_keyphrase_placement(kp, page))
    all_checks.extend(check_cannibalization(site, pages))
    print_table(site, all_checks)
    if args.write:
        path = write_report(site, all_checks, extra="Focus keyphrase analysis", kind="keyphrase")
        print(f"Wrote {path}")
    return 0


def cmd_content(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))

    from aeo_audit.content_check import content_checks
    from aeo_audit.crawl import crawl_site

    cap = args.pages or 20
    print(f"Crawling {site.origin} for content analysis (cap {cap})...")
    pages, _ = crawl_site(site, page_cap=cap, politeness=0.5)
    checks = content_checks(site, pages)
    print_table(site, checks)
    if args.write:
        path = write_report(site, checks, extra="Content quality analysis", kind="content")
        print(f"Wrote {path}")
    return 0


def cmd_consistency(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))

    from aeo_audit.consistency import consistency_checks
    from aeo_audit.crawl import crawl_site

    cap = args.pages or 10
    print(f"Crawling {site.origin} for consistency check (cap {cap})...")
    pages, _ = crawl_site(site, page_cap=cap, politeness=0.5)
    checks = consistency_checks(site, pages)
    print_table(site, checks)
    if args.write:
        path = write_report(site, checks, extra="Entity/fact consistency check", kind="consistency")
        print(f"Wrote {path}")
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    try:
        site = _resolve(args)
    except FleetError as exc:
        return _fail(str(exc))

    from aeo_audit.recommend import format_recommendations, run_recommend, write_recommendations

    print(f"Building recommendations for {site.display_name}...")
    recs, notes = run_recommend(site, with_psi=not args.no_psi)
    if notes:
        print(notes)
        print()
    print(format_recommendations(site, recs))
    if args.write:
        path = write_recommendations(site, recs)
        print(f"Wrote {path}")
    return 0


def _add_site_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "site",
        help="Inventory key, domain (example.com), or URL (https://example.com)",
    )
    parser.add_argument(
        "--entity",
        metavar="NAME",
        default="",
        help="Product name for a one-off domain audit (for example --entity 'Example Widget')",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aeo-audit",
        description="Answer-engine audit. Each check is pass, warn, or fail.",
    )
    parser.add_argument("--version", action="version", version=f"aeo-audit {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create inventory/sites.toml from the example")
    p_init.set_defaults(func=cmd_init)

    p_list = sub.add_parser("list", help="List sites in the inventory")
    p_list.set_defaults(func=cmd_list)

    p_audit = sub.add_parser("audit", help="HTTP and on-page answer-engine audit for one site")
    _add_site_arg(p_audit)
    p_audit.add_argument("--write", action="store_true", help="Write reports/<slug>/YYYY-MM-DD-audit.md")
    p_audit.set_defaults(func=cmd_audit)

    p_crawl = sub.add_parser("crawl", help="Crawl the site and check each HTML page")
    _add_site_arg(p_crawl)
    p_crawl.add_argument("--pages", type=int, default=50, help="Page cap (default 50)")
    p_crawl.add_argument("--delay", type=float, default=1.0, help="Delay between requests, in seconds")
    p_crawl.add_argument("--write", action="store_true")
    p_crawl.set_defaults(func=cmd_crawl)

    p_metas = sub.add_parser("metas", help="Per-page title and meta description audit")
    _add_site_arg(p_metas)
    p_metas.add_argument(
        "--proposed",
        metavar="FILE",
        help="Check proposed titles and metas from JSON, CSV, or a Markdown table",
    )
    p_metas.add_argument("--write", action="store_true")
    p_metas.set_defaults(func=cmd_metas)

    p_schema = sub.add_parser("schema", help="JSON-LD review and official validator URLs")
    _add_site_arg(p_schema)
    p_schema.add_argument("--write", action="store_true")
    p_schema.set_defaults(func=cmd_schema)

    p_prompts = sub.add_parser("prompts", help="Print the buyer prompts to run in answer engines")
    _add_site_arg(p_prompts)
    p_prompts.set_defaults(func=cmd_prompts)

    p_kp = sub.add_parser("keyphrase", help="Focus keyphrase placement and cannibalization")
    _add_site_arg(p_kp)
    p_kp.add_argument("--pages", type=int, default=20)
    p_kp.add_argument("--write", action="store_true")
    p_kp.set_defaults(func=cmd_keyphrase)

    p_content = sub.add_parser("content", help="Answer-first content checks")
    _add_site_arg(p_content)
    p_content.add_argument("--pages", type=int, default=20)
    p_content.add_argument("--write", action="store_true")
    p_content.set_defaults(func=cmd_content)

    p_cons = sub.add_parser(
        "consistency",
        help="Name, phone, hours, and services across pages, schema, and llms.txt",
    )
    _add_site_arg(p_cons)
    p_cons.add_argument("--pages", type=int, default=10)
    p_cons.add_argument("--write", action="store_true")
    p_cons.set_defaults(func=cmd_consistency)

    p_rec = sub.add_parser("recommend", help="Draft fixes ordered by impact and difficulty")
    _add_site_arg(p_rec)
    p_rec.add_argument("--write", action="store_true")
    p_rec.add_argument("--no-psi", action="store_true", help="Skip PageSpeed even if a key is set")
    p_rec.set_defaults(func=cmd_recommend)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
