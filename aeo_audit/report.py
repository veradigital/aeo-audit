"""Pass / warn / fail tables and markdown for one site."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from aeo_audit.audit import score
from aeo_audit.config import Site, data_root
from aeo_audit.http import Check


def print_table(site: Site, checks: list[Check]) -> None:
    passed, warn, fail = score(checks)
    print(f"{site.display_name}  {site.origin}")
    print(f"pass {passed}  warn {warn}  fail {fail}")
    print()
    if not checks:
        return
    width = max(len(c.title) for c in checks)
    for check in checks:
        mark = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}[
            check.status
        ]
        print(f"{mark:4}  {check.title:<{width}}  {check.evidence}")


def markdown_report(
    site: Site,
    checks: list[Check],
    extra: str = "",
    command: str = "aeo-audit",
) -> str:
    passed, warn, fail = score(checks)
    today = date.today().isoformat()
    lines = [
        f"# AEO audit — {site.display_name} — {today}",
        "",
        f"Site: {site.origin}  ",
        f"Stack: {site.stack or 'unknown'}  ",
        f"Score: **{passed} pass / {warn} warn / {fail} fail**",
        "",
        "This is an update-in-place audit. It does not recommend a greenfield rebuild.",
        "",
        "## Checks",
        "",
        "| Status | Check | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        ev = check.evidence.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {check.status.upper()} | {check.title} | {ev} |")
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    if fails or warns:
        lines += ["", "## What to do, and the likely impact", ""]
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
    if extra:
        lines += ["", extra]
    lines += [
        "",
        "## Next",
        "",
        "1. Apply the failures on the existing site (see `playbooks/apply.md`).",
        f"2. Run `{command} prompts {site.slug}` and record mention, citation, and accuracy.",
        f"3. Re-run `{command} audit {site.slug} --write` and diff this file.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_report(
    site: Site,
    checks: list[Check],
    extra: str = "",
    kind: str = "audit",
    command: str = "aeo-audit",
) -> Path:
    folder = data_root() / "reports" / site.slug
    folder.mkdir(parents=True, exist_ok=True)
    slug = kind if kind else "audit"
    path = folder / f"{date.today().isoformat()}-{slug}.md"
    path.write_text(markdown_report(site, checks, extra, command=command))
    return path
