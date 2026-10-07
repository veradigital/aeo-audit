# Apply playbook (update the existing site)

Audit first. Then change the live site. Do not scaffold a new Next app unless the user explicitly asked for a rebuild.

## Order

1. **Stop the leaks** — staging hosts out of `llms.txt`, JSON-LD `@id`, canonicals, internal links.
2. **Stay snippet-eligible** — no `nosnippet`, no `max-snippet:0`. In Search Console, Settings → Search generative AI stays on include.
3. **Tell the truth in the chrome** — title, meta, H1, org/product schema. Schema is for rich results and entity clarity. It is not an AI Overview switch.
4. **Give the non-Google engines a brief** — hand-authored `/llms.txt`. Google Search does not read it.
5. **Give readers answers on pages that already rank** — one visible FAQ, matching FAQPage once. Do not publish a new URL for every related query.
6. **Align names** — one product name, old aliases explained once, not used as if current.
7. **Re-audit** — `aeo-audit audit SITE --write` and append the prompt table.

## Rules

- Facts only. No invented prices, ratings, or customer quotes.
- Visible HTML must match JSON-LD and `llms.txt`. Drift is a fail.
- One canonical FAQ URL. Do not emit FAQPage on Contact as well.
- Never `aggregateRating` copied from reviews.
- Prefer editing the CMS / theme / SEO plugin the site already has.
- WordPress + Pantheon + Yoast: see [platforms.md](platforms.md). Next/other: same facts, different file.

## What “done” means for a pass

- CLI fail count dropped; remaining fails have a written reason.
- Production host only in llms + schema.
- FAQ live with matching schema.
- Title/meta name the current offer.
- `aeo-audit schema SITE --write` re-run. Schema Markup Validator: 0 errors on home, product, one article. Rich Results Test crawled successfully; types match the page (Organization eligible or explained; SoftwareApplication on the product URL or a written reason if price is unpublished; Article on posts; Breadcrumbs ok).
- Prompt set re-run (even if mention rate is still low — we need the after snapshot).
