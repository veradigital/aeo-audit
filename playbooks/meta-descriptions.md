# Meta description and title tag playbook

Rules for the per-page meta/title audit (`aeo-audit metas SITE`). Each rule is pass/warn/fail with a reason. No composite score.

## Why this matters

Meta descriptions and title tags are the first thing answer engines, Google, and humans see. Google rewrites mismatched or keyword-stuffed snippets. AI engines quote title/meta as the entity label. Missing or duplicate metas mean the engine chooses the snippet — usually worse than what you'd write.

A homepage-only check misses pages that have no meta description. This audit reads the sitemap.

## Commands

```bash
# Live audit: crawl sitemap, check every indexable page
aeo-audit metas SITE --write

# Proposed metas: check a draft file before applying (JSON, CSV, or Markdown table)
aeo-audit metas SITE --proposed FILE --write
```

Output goes to `reports/<slug>/YYYY-MM-DD-metas.md` and `.json`.

## Meta description rules

### Length (automated)

| Band | Status | Why |
| --- | --- | --- |
| < 50 chars | **FAIL** | Too short to say anything useful. Google will almost certainly replace it. |
| 50–99 chars | **WARN** | Under 100 chars. Usable but wastes SERP real estate. |
| 100–119 chars | **WARN** | Under the 120-char target. Mobile truncates around 120 chars, so the key message should be there. |
| **120–156 chars** | **PASS** | Target range. Fits mobile and desktop. Yoast green bar. Consistent with `content.md` and the 120–156 character target. |
| 157–160 chars | **WARN** | May be truncated on mobile. Desktop usually shows ~155–160. |
| > 160 chars | **FAIL** | Will be truncated on desktop. |

Thresholds are configurable per site in `[site.meta_rules]`.

### Missing meta description (automated)

**FAIL.** A page with no `<meta name="description">` tag lets Google (and every AI engine) auto-generate the snippet. That auto-snippet is almost always worse. Pages where the only description is `og:description` (Yoast auto-excerpt) also fail — they need a hand-written meta.

### Product / entity name (automated)

- **FAIL** on product-defining pages (homepage and main product page) if the product name is missing from the description. These pages teach AI what the brand sells.
- **PASS** (optional) on industry, service, resource, and about pages. The page should lead with its own topic phrase. Including the product name is good but not required.

Which pages are product-defining is configured in `product_required_pages`.

### Focus phrase (automated)

The meta should contain the page title's main phrase (the text before the pipe/dash separator, or a per-page override in `focus_phrases`). This is the closest proxy for the Yoast keyphrase, which isn't public.

- **PASS** if the full phrase appears.
- **WARN** if only a partial match (≥60% of words).
- **WARN** if missing entirely.

### Spelling rules (automated)

Site-specific canonical spellings. Example: the product name is "Widget Pro", so flag "WidgetPro". Configured in `[site.meta_rules.spelling_rules]`.

**FAIL** on any spelling violation.

### Claim phrasing (automated)

Site-specific patterns for claims that must follow a specific form. Example: if `facts.md` locks a claim as "up to 30%", a bare "30% faster" is a fact-lock violation.

**FAIL** on match.

### Banned superlatives (automated)

Unsupported puffery that isn't a locked fact: "industry-leading", "world-class", "best-in-class". Configured per site.

**WARN.** Low risk, but not citable and not verifiable.

### Unique per page (automated)

**FAIL** if two or more indexable pages share the same meta description. Duplicates split the signal and confuse engines about which page to recommend. A redirect, a noindex URL, or a page whose canonical points elsewhere is not a second page.

### Auto-excerpt detection (automated)

**WARN** if the meta matches the opening ~80 chars of the page body. This usually means the SEO plugin auto-generated it from the content rather than having a hand-written description.

### Double quotes and special characters (automated)

**WARN** on double quotes (`"`) in the meta — they can break the HTML `content=""` attribute or display oddly in SERPs. Also flag unescaped `<` or `>`.

### Keyword stuffing (automated, heuristic)

**WARN** if the meta reads like a comma-separated keyword list rather than a natural sentence (high comma-to-word ratio), or if it has no clear differentiator or call to action.

### Content match (automated, heuristic)

Cross-checks that the meta's key terms (4+ letter words) appear in the page body or H1. If less than 30% match, Google is likely to rewrite the snippet.

**WARN** if match ratio is low. This is a heuristic — review manually if warned.

### City / service area (automated, configurable)

For local or service-area businesses: **WARN** if the city or service-area terms don't appear naturally in the meta. **Off by default.** Enable with `require_city = true` and `city_terms = ["Springfield", "Riverside"]` in site config.

Leave it off for a national or global brand that does not sell in one city.

### Duplicate meta tags (automated)

**FAIL** if the rendered HTML contains more than one `<meta name="description">` tag. Common cause: theme outputs a meta description AND Yoast/RankMath also outputs one. Check the rendered HTML, not just the CMS field.

### OG tag consistency (automated)

- **WARN** if `og:description` is missing or differs from the meta description.
- **WARN** if `og:title` is missing or differs from `<title>`.

Social sharing and some AI crawlers use OG tags. They should be consistent with the primary tags.

### Search intent match (manual check)

**Cannot be fully automated.** After the automated audit, a human should verify:

- Each meta accurately describes the page's actual content and matches the search intent a visitor would have.
- Google rewrites mismatched or keyword-stuffed snippets. If the meta doesn't match the page, it's wasted effort.
- Each meta contains one clear differentiator or next step, not just a keyword list.

## Title tag rules

### Length (automated)

| Band | Status | Why |
| --- | --- | --- |
| < 15 chars | **FAIL** | Too short to be a real title. |
| 15–29 chars | **WARN** | Short. |
| **30–60 chars** | **PASS** | Target range. Fits the ~580px Google SERP title area. |
| 61–70 chars | **WARN** | May be truncated; depends on character width. |
| > 70 chars | **FAIL** | Will be truncated. |

### Pixel width (automated, heuristic)

Titles are truncated by pixel width (~580px on desktop), not character count. The audit estimates pixel width using per-character averages. **WARN** if the estimate exceeds 580px.

This is a rough estimate — actual rendering depends on the font Google uses on the day. Character count is the primary check; pixel width is supplemental.

### Product / brand on product-defining pages (automated)

**FAIL** if the product name is missing from the title on a product page listed in `product_required_pages`. The homepage is the exception: its title is the category (`Warehouse Software | Example Co`), and the product name belongs in the homepage description. Putting the product name in both titles makes them duplicates.

### Brand at end with separator (automated)

Titles should follow the pattern "Main Phrase | Brand Name" (or with – / — / -). The main topic phrase comes first for keyword prominence; the brand anchors trust at the end.

**WARN** if the short brand isn't at the end after a separator. `brand_suffix` is used as written when it is 18 characters or shorter. A longer legal name, such as `Example Co`, is shortened to the first word of the site name (`Example Co`) so the title stays inside 60 characters.

### H1 match (automated)

**WARN** if the title is identical to the H1 word-for-word. The title and H1 should share the focus phrase but not be exact copies — the title is for SERPs, the H1 is for the page visitor.

### Unique per page (automated)

**FAIL** if two indexable pages share the same title. Redirects and other non-indexable URLs are left out of this comparison.

### Focus phrase position (automated)

**WARN** if the main phrase appears after the separator rather than before it. The focus topic should come first.

### Spelling rules (automated)

Same spelling rules as meta descriptions. **FAIL** on violation.

## Non-indexable pages

Pages that are `noindex`, redirect to another URL, or have a canonical pointing elsewhere:

- All meta/title rules are marked **SKIP** (N/A). There's no point auditing the meta of a page Google won't index.
- A `noindex` page that appears in the sitemap is still a **FAIL** for `sitemap-noindex` — the sitemap and the robots directive contradict each other.

## Configuration

All thresholds are configurable per site in `inventory/sites.toml` under `[site.meta_rules]`:

```toml
[example.meta_rules]
product_required_pages = ["/", "/product/"]
brand_suffix = "Example Co"
require_city = false
banned_superlatives = ["industry-leading", "world-class"]
claim_pattern = '(?<![Uu]p to )\b\d+%'

[example.meta_rules.spelling_rules]
"WidgetPro" = "Widget Pro"

[example.meta_rules.focus_phrases]
"/resources/" = "setup guides"
```

Omit the section entirely to use the defaults (120–156 meta, ≤60 title, no spelling/claim/city rules).

## Proposed meta workflow

Before publishing new metas, check them against the rules:

1. Prepare a file with one row per page: URL + proposed meta (+ optional title). JSON, CSV, or Markdown table format.
2. Run `aeo-audit metas SITE --proposed FILE --write`.
3. Fix FAILs and review WARNs.
4. Apply to the live site.
5. Re-run `aeo-audit metas SITE --write` to confirm live.

### File formats

**JSON** (array of objects):
```json
[
  {"url": "https://example.com/", "meta": "Proposed description here.", "title": "Optional title"},
  {"url": "https://example.com/about/", "meta": "About page description."}
]
```

**CSV** (columns: url, meta, title):
```csv
url,meta,title
https://example.com/,Proposed description here.,Optional title
https://example.com/about/,About page description.,
```

**Markdown** (pipe table):
```markdown
| url | meta | title |
| --- | --- | --- |
| https://example.com/ | Proposed description here. | Optional title |
```

## Scheduled audits

To run the meta audit on a schedule (e.g., weekly via GitHub Actions):

```yaml
name: Meta audit
on:
  schedule:
    - cron: '0 9 * * 1'  # Monday 9 AM UTC
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: |
          for site in example; do
            ./bin/aeo-audit metas "$site" --write || true
          done
      - uses: actions/upload-artifact@v4
        with:
          name: meta-reports
          path: reports/*/????-??-??-metas*
```

This does **not** auto-commit to main. Reports are uploaded as artifacts for human review.
