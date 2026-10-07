from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class FleetError(Exception):
    pass


def data_root() -> Path:
    """Directory that holds inventory/ and reports/.

    ``AEO_DATA_DIR`` wins. Otherwise the nearest parent of the working
    directory that already has ``inventory/sites.toml``. Otherwise the
    working directory, so a fresh ``init`` does not write into the install.
    """
    env = os.environ.get("AEO_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "inventory" / "sites.toml").is_file():
            return candidate
        if candidate == Path.home() or candidate.parent == candidate:
            break
    return cwd


def bundled_example() -> Path:
    """Example inventory shipped with the package."""
    candidate = Path(__file__).resolve().parent.parent / "inventory" / "sites.example.toml"
    if candidate.is_file():
        return candidate
    raise FleetError("sites.example.toml is missing from the aeo-audit install")


def _looks_like_domain_or_url(name: str) -> bool:
    """True if *name* looks like a domain (example.com) or URL rather than
    an inventory slug."""
    return "." in name and " " not in name


@dataclass
class MetaRules:
    """Per-site meta/title audit thresholds. Sensible defaults can be
    overridden in ``[site.meta_rules]`` inside ``sites.toml``."""

    # --- meta description length bands ---
    meta_len_fail_low: int = 50
    meta_len_warn_low: int = 120
    meta_len_target_low: int = 120
    meta_len_target_high: int = 156
    meta_len_warn_high: int = 160
    meta_len_fail_high: int = 160

    # --- title length bands ---
    title_len_fail_low: int = 15
    title_len_warn_low: int = 30
    title_len_target_high: int = 60
    title_len_fail_high: int = 70

    # --- page types where the product / entity name is REQUIRED ---
    product_required_pages: list[str] = field(default_factory=lambda: ["/"])

    # --- spelling and claim rules ---
    spelling_rules: dict[str, str] = field(default_factory=dict)
    claim_pattern: str = ""
    banned_superlatives: list[str] = field(default_factory=list)

    # --- per-page focus phrase overrides (path → phrase) ---
    focus_phrases: dict[str, str] = field(default_factory=dict)

    # --- brand / separator expected at end of title ---
    # A short value is used as written. A long legal name is shortened to the
    # first word of the site name so titles stay inside 60 characters.
    brand_suffix: str = ""

    # --- local / service-area: require city in meta (off by default) ---
    require_city: bool = False
    city_terms: list[str] = field(default_factory=list)

    # --- pixel-width estimate for title truncation (~10.3 px/char avg) ---
    title_pixel_limit: int = 580


@dataclass
class Competitor:
    name: str
    url: str = ""
    place_id: str = ""


@dataclass
class PageKeyphrase:
    path: str
    keyphrase: str


@dataclass
class Site:
    slug: str
    url: str
    name: str = ""
    product: str = ""
    stack: str = "other"
    host: str = ""
    vertical: str = ""
    city: str = ""
    service_area: list[str] = field(default_factory=list)
    money_action: str = ""
    key_pages: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    tier: str = "found"
    gsc_property: str = ""
    gbp_location: str = ""
    gbp_account: str = ""
    competitors: list[Competitor] = field(default_factory=list)
    page_keyphrases: list[PageKeyphrase] = field(default_factory=list)
    phone: str = ""
    hours: str = ""
    services: list[str] = field(default_factory=list)
    meta_rules: MetaRules = field(default_factory=MetaRules)

    @property
    def origin(self) -> str:
        return self.url.rstrip("/")

    @property
    def display_name(self) -> str:
        return self.name or self.slug


def short_brand(site: Site) -> str:
    """Brand that belongs at the end of a title.

    ``brand_suffix`` is used as written when it is 18 characters or shorter.
    A longer legal name is shortened to the first word of the site name.
    """
    suffix = (site.meta_rules.brand_suffix or site.name or "").strip()
    if suffix and len(suffix) <= 18:
        return suffix
    source = (site.name or suffix).strip()
    return source.split()[0] if source else "the company"


def _parse_competitors(raw: list) -> list[Competitor]:
    out: list[Competitor] = []
    for item in raw:
        if isinstance(item, str):
            out.append(Competitor(name=item))
        elif isinstance(item, dict):
            out.append(Competitor(
                name=str(item.get("name", "")),
                url=str(item.get("url", "")),
                place_id=str(item.get("place_id", "")),
            ))
    return out


def _parse_keyphrases(raw: list) -> list[PageKeyphrase]:
    out: list[PageKeyphrase] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(PageKeyphrase(
                path=str(item.get("path", "/")),
                keyphrase=str(item.get("keyphrase", "")),
            ))
    return out


def _parse_meta_rules(raw: dict) -> MetaRules:
    mr = raw.get("meta_rules")
    if not mr or not isinstance(mr, dict):
        return MetaRules()
    kwargs: dict = {}
    int_fields = {
        "meta_len_fail_low", "meta_len_warn_low", "meta_len_target_low",
        "meta_len_target_high", "meta_len_warn_high", "meta_len_fail_high",
        "title_len_fail_low", "title_len_warn_low", "title_len_target_high",
        "title_len_fail_high", "title_pixel_limit",
    }
    for k in int_fields:
        if k in mr:
            kwargs[k] = int(mr[k])
    if "product_required_pages" in mr:
        kwargs["product_required_pages"] = list(mr["product_required_pages"])
    if "spelling_rules" in mr and isinstance(mr["spelling_rules"], dict):
        kwargs["spelling_rules"] = {str(k): str(v) for k, v in mr["spelling_rules"].items()}
    if "claim_pattern" in mr:
        kwargs["claim_pattern"] = str(mr["claim_pattern"])
    if "banned_superlatives" in mr:
        kwargs["banned_superlatives"] = list(mr["banned_superlatives"])
    if "focus_phrases" in mr and isinstance(mr["focus_phrases"], dict):
        kwargs["focus_phrases"] = {str(k): str(v) for k, v in mr["focus_phrases"].items()}
    if "brand_suffix" in mr:
        kwargs["brand_suffix"] = str(mr["brand_suffix"])
    if "require_city" in mr:
        kwargs["require_city"] = bool(mr["require_city"])
    if "city_terms" in mr:
        kwargs["city_terms"] = list(mr["city_terms"])
    return MetaRules(**kwargs)


def load_sites(path: Path | None = None) -> dict[str, Site]:
    _load_dotenv()
    root = data_root()
    inventory = path or (root / "inventory" / "sites.toml")
    if not inventory.exists():
        try:
            shown = inventory.relative_to(root)
        except ValueError:
            shown = inventory
        raise FleetError(f"Missing {shown}. Run: aeo-audit init")
    data = tomllib.loads(inventory.read_text())
    sites: dict[str, Site] = {}
    for slug, raw in data.items():
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url:
            raise FleetError(f"[{slug}] needs a url")
        tier = str(raw.get("tier") or "").strip().lower()
        sites[slug] = Site(
            slug=slug,
            url=url,
            name=str(raw.get("name") or ""),
            product=str(raw.get("product") or ""),
            stack=str(raw.get("stack") or "other"),
            host=str(raw.get("host") or ""),
            vertical=str(raw.get("vertical") or ""),
            city=str(raw.get("city") or ""),
            service_area=list(raw.get("service_area") or []),
            money_action=str(raw.get("money_action") or ""),
            key_pages=list(raw.get("key_pages") or ["/"]),
            prompts=list(raw.get("prompts") or []),
            tier=tier,
            gsc_property=str(raw.get("gsc_property") or ""),
            gbp_location=str(raw.get("gbp_location") or ""),
            gbp_account=str(raw.get("gbp_account") or ""),
            competitors=_parse_competitors(raw.get("competitors") or []),
            page_keyphrases=_parse_keyphrases(raw.get("page_keyphrases") or []),
            phone=str(raw.get("phone") or ""),
            hours=str(raw.get("hours") or ""),
            services=list(raw.get("services") or []),
            meta_rules=_parse_meta_rules(raw),
        )
    return sites


def _domain_slug(url: str) -> str:
    """Derive a filesystem-safe slug from a domain or URL."""
    host = urlparse(url).netloc or urlparse("https://" + url).netloc or url
    host = host.lower().lstrip("www.")
    return re.sub(r"[^a-z0-9.-]", "-", host).strip("-") or "unknown"


def site_from_domain(
    name: str,
    *,
    entity: str = "",
) -> Site:
    """Build an ad-hoc ``Site`` from a bare domain or URL with sensible
    defaults.  No site-specific style rules unless *entity* is provided."""
    raw = name.strip()
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc or parsed.path.split("/")[0]
    origin = f"{parsed.scheme}://{host}"
    slug = _domain_slug(raw)
    rules = MetaRules(product_required_pages=["/"])
    product = entity or ""
    return Site(
        slug=slug,
        url=origin,
        name=entity or host,
        product=product,
        key_pages=["/"],
        meta_rules=rules,
    )


def resolve_site(name: str, sites: dict[str, Site] | None = None) -> Site:
    sites = sites or load_sites()
    key = name.strip().lower()
    if key in sites:
        return sites[key]
    matches = [
        s
        for slug, s in sites.items()
        if key in slug or key in s.name.lower() or key in s.url.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    known = ", ".join(sorted(sites)) or "(none)"
    raise FleetError(f"Unknown site {name!r}. Known: {known}")


def resolve_site_or_domain(
    name: str,
    *,
    entity: str = "",
) -> Site:
    """Try inventory first; if the name looks like a domain/URL and isn't
    found, build an ad-hoc Site."""
    try:
        sites = load_sites()
    except FleetError:
        sites = {}
    key = name.strip().lower()
    if key in sites:
        return sites[key]
    matches = [
        s
        for slug, s in sites.items()
        if key in slug or key in s.name.lower() or key in s.url.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if _looks_like_domain_or_url(name):
        return site_from_domain(name, entity=entity)
    known = ", ".join(sorted(sites)) or "(none)"
    raise FleetError(f"Unknown site {name!r}. Known: {known}")


_dotenv_loaded = False


def _load_dotenv() -> None:
    """Load repo .env into the environment once. Existing vars win. Never print values."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    path = data_root() / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def env_key(name: str) -> str:
    """Return an env var value or empty string. Never log or print the value."""
    _load_dotenv()
    return os.environ.get(name, "")


_load_dotenv()
