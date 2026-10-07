# Schema review (required on every audit)

Valid structured data keeps the public name, address, and product consistent, and it can unlock a Google Search feature when that feature still exists. It is not required for Google AI Overviews or AI Mode. A page that looks product-led in HTML can still teach a services firm on a hosting URL in JSON-LD. That host leak hurts every engine.

## Tools (run both — they answer different questions)

| Tool | URL | What it confirms |
| --- | --- | --- |
| **Schema Markup Validator** | https://validator.schema.org/ | Markup is valid schema.org. 0 errors is the bar. Warnings are optional cleanup. |
| **Google Rich Results Test** | https://search.google.com/test/rich-results | Which *Google* features this URL is eligible for (Organization, Article, Breadcrumb, Software app, Local business). |

Print both URLs with the page filled in:

```
https://validator.schema.org/#url={PAGE}
https://search.google.com/test/rich-results?url={PAGE}
```

CLI: `aeo-audit schema SITE --write` extracts JSON-LD, POSTs each 200 URL to the Schema Markup Validator, flags gaps, and prints both official links. **The agent must still open Google Rich Results Test** on the homepage, the product/money page, and one article — there is no public Rich Results API. Paste detected rich-result types into `reports/<slug>/YYYY-MM-DD-schema.md`. Extraction alone is not confirmation.

### Google vs AI

Google dropped **FAQ rich results** in May 2026. AI Overviews and AI Mode do not require `FAQPage`, `llms.txt`, or any special AI markup. Keep one `FAQPage` when the questions are visible, so the JSON-LD matches the page and other answer engines can quote it. Do not add a second FAQPage on the same URL. Do not treat a Rich Results Test “no FAQ detected” as a reason to invent extra schema for Google AI.

`SoftwareApplication` rich results require `name` + `offers.price`. If the product is paid and there is no public price, **do not invent $0 or a dollar amount**. Emit SoftwareApplication with name, description, url, category, and `offers.url` pointing at the contact/demo page. Expect a Rich Results warning on price; that is acceptable. The type still helps AI resolve the product.

Never emit `aggregateRating` from copied reviews.

## What goes on which page

Not one blob on every URL.

| Page | Types | Must include |
| --- | --- | --- |
| Home / About | `Organization` (or a tighter subtype). Yoast `WebPage` + `WebSite` + `BreadcrumbList` stay. | Public `url` + `@id` on the **canonical host**. `name`, `logo`, `description`. `telephone`, `email`, `address` when known. `sameAs` to real profiles (LinkedIn, store listing, YouTube) — not only leftover Facebook/X. |
| Product | `SoftwareApplication` (or `Product`) **plus** Organization | `name` = current product. `url` = product page. Linked from Organization. |
| FAQ | `FAQPage` once, on the canonical FAQ URL | Visible answers == JSON-LD == `llms.txt`. No duplicate FAQPage on Contact. |
| Articles | `Article` / `BlogPosting` | `headline`, dates, `image`, `author` + `publisher` on the **public** host. |
| Contact | Organization / ContactPoint as needed | Same NAP as the page. |

`WebPage` + `WebSite` + `BreadcrumbList` alone is the Yoast default. That is not enough.

## Fail conditions

- Any `pantheonsite.io`, `wpenginepowered.com`, or other host leak in `@id` / `url` / `author` / `publisher`
- Organization `url` ≠ public origin
- Product page has no SoftwareApplication/Product when inventory `product` is set
- Article author/publisher IDs on a staging host
- Schema.org validator **errors** (not warnings)
- Rich Results Test crawl failure or parse errors

## After apply

Re-run `aeo-audit schema SITE --write`. Re-open both validators on the same three URLs. Paste detected types + error counts into `schema.md`. Do not call schema done on extraction only.
