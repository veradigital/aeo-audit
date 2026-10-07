from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass

CURL = shutil.which("curl") or "/usr/bin/curl"
UA = "AEO-Audit/0.1 (+https://github.com/veradigital/aeo-audit)"

LEAK_HOSTS = (
    "pantheonsite.io",
    "wpenginepowered.com",
    "cloudwaysapps.com",
    "myshopify.com",
    "localhost",
    ".local/",
    "127.0.0.1",
)

AI_BOTS = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-Web",
    "anthropic-ai",
    "Google-Extended",
    "PerplexityBot",
    "Perplexity-User",
    "Applebot-Extended",
    "CCBot",
    "cohere-ai",
    "meta-externalagent",
)


@dataclass
class Fetch:
    url: str
    status: int
    final_url: str
    headers: dict[str, str]
    body: str
    error: str = ""


@dataclass
class Check:
    id: str
    status: str  # pass | fail | warn | skip
    title: str
    evidence: str
    impact: str = ""
    fix: str = ""


def fetch(url: str, timeout: int = 25) -> Fetch:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        hdr = f"{tmp}/h"
        body_path = f"{tmp}/b"
        cmd = [
            CURL,
            "-sL",
            "-A",
            UA,
            "--max-time",
            str(timeout),
            "-D",
            hdr,
            "-o",
            body_path,
            "-w",
            "%{http_code} %{url_effective}",
            url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except OSError as exc:
            return Fetch(url, 0, url, {}, "", str(exc))
        meta = (proc.stdout or "").strip().split()
        status = 0
        final = url
        if meta:
            try:
                status = int(meta[0])
            except ValueError:
                status = 0
            if len(meta) > 1:
                final = meta[1]
        header_blob = ""
        body = ""
        try:
            header_blob = open(hdr, encoding="utf-8", errors="replace").read()
            body = open(body_path, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
        hops = re.split(r"(?i)HTTP/\d(?:\.\d)?\s+", header_blob)
        last_headers = hops[-1] if hops else header_blob
        headers = {}
        for line in last_headers.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        return Fetch(
            url=url,
            status=status,
            final_url=final,
            headers=headers,
            body=body,
            error=(proc.stderr or "").strip(),
        )


def abs_url(origin: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return origin.rstrip("/") + "/" + path.lstrip("/")


def first_tag(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def all_tags(html: str, pattern: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>", "", re.sub(r"\s+", " ", m)).strip()
        for m in re.findall(pattern, html, re.I | re.S)
    ]


def jsonld_types(html: str) -> list[str]:
    blobs = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )
    types: list[str] = []

    def walk(node) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        t = node.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
        if "@graph" in node:
            walk(node["@graph"])
        for key in ("about", "publisher", "mainEntity", "author"):
            if key in node:
                walk(node[key])

    for blob in blobs:
        try:
            walk(json.loads(blob))
        except json.JSONDecodeError:
            types.append("PARSE_FAIL")
    return types


def leak_hits(text: str) -> list[str]:
    low = text.lower()
    return [host for host in LEAK_HOSTS if host in low]
