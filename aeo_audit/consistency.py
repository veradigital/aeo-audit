"""Entity/fact consistency — name, phone, hours, services across pages, schema, llms.txt, GBP."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from aeo_audit.config import Site
from aeo_audit.crawl import PageData
from aeo_audit.http import Check, abs_url, fetch


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_schema_org_fields(html: str) -> list[dict]:
    """Extract Organization/LocalBusiness nodes from JSON-LD."""
    blobs = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.I | re.S,
    )
    org_nodes: list[dict] = []
    for blob in blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        nodes = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
        if isinstance(data, dict) and "@graph" in data:
            nodes.extend(data["@graph"])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            t = node.get("@type", "")
            types = t if isinstance(t, list) else [t]
            from aeo_audit.schema import ORG_TYPES
            if any(str(tp) in ORG_TYPES for tp in types):
                org_nodes.append(node)
    return org_nodes


def _normalize_phone(phone: str) -> str:
    return re.sub(r"[^\d+]", "", phone)


def consistency_checks(
    site: Site,
    pages: list[PageData],
    page_html: dict[str, str] | None = None,
    gbp_data: dict | None = None,
) -> list[Check]:
    checks: list[Check] = []
    html_map = page_html or {}

    expected_name = site.name
    expected_phone = _normalize_phone(site.phone) if site.phone else ""
    expected_hours = site.hours
    expected_services = [s.lower() for s in site.services]

    schema_names: list[tuple[str, str]] = []
    schema_phones: list[tuple[str, str]] = []
    page_phones: list[tuple[str, str]] = []
    page_names: list[tuple[str, str]] = []

    for page in pages:
        if page.status >= 400:
            continue

        html = html_map.get(page.url, "")
        if not html:
            continue
        path = urlparse(page.url).path

        org_nodes = _extract_schema_org_fields(html)
        for org in org_nodes:
            s_name = org.get("name", "")
            if s_name:
                schema_names.append((path, s_name))
            s_phone = org.get("telephone", "")
            if s_phone:
                schema_phones.append((path, s_phone))

        body = _strip_html(html)

        if expected_phone:
            phone_patterns = re.findall(r"[\(]?\d{3}[\)]?[\s.-]?\d{3}[\s.-]?\d{4}", body)
            for p in phone_patterns:
                norm = _normalize_phone(p)
                if norm != expected_phone:
                    page_phones.append((path, p))

    if expected_name:
        for path, s_name in schema_names:
            if s_name.lower().strip() != expected_name.lower().strip():
                if expected_name.lower().split()[0] not in s_name.lower():
                    checks.append(Check(
                        f"consistency:name:{path}",
                        "warn",
                        f"Business name mismatch: {path}",
                        f'Schema says "{s_name}", inventory says "{expected_name}"',
                        "Inconsistent business name weakens entity resolution.",
                        "Use the same legal name everywhere.",
                    ))

    if expected_phone:
        for path, s_phone in schema_phones:
            if _normalize_phone(s_phone) != expected_phone:
                checks.append(Check(
                    f"consistency:phone:schema:{path}",
                    "fail",
                    f"Phone mismatch in schema: {path}",
                    f'Schema: {s_phone}, expected: {site.phone}',
                    "Wrong phone in structured data confuses Google and loses calls.",
                    "Update the Organization telephone field.",
                ))
        for path, p_phone in page_phones:
            checks.append(Check(
                f"consistency:phone:page:{path}",
                "warn",
                f"Different phone on page: {path}",
                f'Found {p_phone}, expected {site.phone}',
                "Multiple phone numbers confuse customers and AI.",
                "Standardize to one phone number.",
            ))

    llms_f = fetch(abs_url(site.origin, "/llms.txt"))
    if 200 <= llms_f.status < 400 and llms_f.body.strip():
        llms_text = llms_f.body.lower()
        if expected_name and expected_name.lower() not in llms_text:
            first_word = expected_name.split()[0].lower() if expected_name else ""
            if first_word and first_word not in llms_text:
                checks.append(Check(
                    "consistency:llms:name",
                    "warn",
                    "Business name in llms.txt",
                    f'"{expected_name}" not found in /llms.txt',
                    "llms.txt should reference the business name.",
                    "Add the business name to llms.txt.",
                ))

        if expected_phone:
            if _normalize_phone(site.phone) not in _normalize_phone(llms_f.body):
                checks.append(Check(
                    "consistency:llms:phone",
                    "warn",
                    "Phone in llms.txt",
                    f"Phone {site.phone} not in /llms.txt",
                    "Contact details should be in llms.txt for answer engines.",
                    "Add the phone number to llms.txt.",
                ))

        if expected_services:
            missing_svc = [s for s in expected_services if s not in llms_text]
            if len(missing_svc) > len(expected_services) // 2:
                checks.append(Check(
                    "consistency:llms:services",
                    "warn",
                    "Services in llms.txt",
                    f"Missing: {', '.join(missing_svc[:5])}",
                    "Services listed in inventory should appear in llms.txt.",
                    "Add key services to the llms.txt brief.",
                ))

    if gbp_data:
        gbp_name = gbp_data.get("name", "")
        gbp_phone = gbp_data.get("phone", "")
        if gbp_name and expected_name:
            if gbp_name.lower().strip() != expected_name.lower().strip():
                checks.append(Check(
                    "consistency:gbp:name",
                    "warn",
                    "GBP name vs inventory",
                    f'GBP: "{gbp_name}", inventory: "{expected_name}"',
                    "Mismatched names across GBP and website hurt local SEO.",
                    "Align the GBP name with the website.",
                ))
        if gbp_phone and expected_phone:
            if _normalize_phone(gbp_phone) != expected_phone:
                checks.append(Check(
                    "consistency:gbp:phone",
                    "fail",
                    "GBP phone vs inventory",
                    f'GBP: {gbp_phone}, expected: {site.phone}',
                    "Phone mismatch between GBP and website loses calls and breaks NAP.",
                    "Update the GBP phone to match.",
                ))

    if not checks:
        checks.append(Check(
            "consistency",
            "pass",
            "Entity consistency",
            "No contradictions found in available data",
        ))

    return checks
