# AEO/GEO baseline for new sites

Rules for shipping the AI-visibility layer on a new local/service-business
site. These complement the existing audit checks (`aeo-audit audit`) —
which verify an existing site — with build-time requirements for sites
that don't exist yet.

Use this while building a site. `aeo-audit audit` checks the same items after the site is live.

---

## 1. Snippet eligibility

Production pages must not carry `noindex`, `none`, `nosnippet`, or
`max-snippet:0`. Draft and utility pages stay `noindex`.

- `noindex` keeps the URL out of Google Search entirely.
- `nosnippet` and `max-snippet:0` block Google AI Overviews, AI Mode,
  and the normal snippet.
- Google Search ignores `/llms.txt`. It does not use FAQPage, special
  AI markup, or `/llms.txt` to decide AI Overviews.

Canonicals must use the public domain, not a preview host.

## 2. Robots / AI-crawler access

`User-agent: *` with `Allow: /` is enough. Do **not** add a sitewide
`Disallow` for answer-engine crawlers:

- OAI-SearchBot, ChatGPT-User
- Claude-SearchBot, Claude-User
- PerplexityBot, Perplexity-User

A `Disallow` on GPTBot, ClaudeBot, or Google-Extended only limits
**training**. It does not remove the site from Google AI Overviews.
Do not add named `Allow` lines as a feature — `User-agent: *` already
allows.

See also: `aeo-audit audit` Layer 1 "Answer crawlers not blocked" gate.

## 3. FAQ placement and FAQPage

- Ship 6–10 real buyer questions with 1–3 factual-sentence answers,
  visible on `/faq` (or an equivalent canonical FAQ URL).
- One `FAQPage` JSON-LD block on that URL, matching the visible
  questions. Do not add a second `FAQPage` on Contact or any other page.
- Google dropped FAQ rich results in May 2026 and does not use `FAQPage`
  for AI Overviews. ChatGPT, Claude, and Perplexity still quote a
  matching FAQ more reliably when the visible text and the JSON-LD agree.
- When the page answers from a script in the browser, also put the
  same answers in the HTML, such as a collapsed "Browse all answers"
  block, so a crawler can read them.
- FAQ page needs `alternates.canonical`.
- Answers must be consistent across the visible page, the `FAQPage`
  JSON-LD, and `/llms.txt`.

See also: [schema.md](schema.md) for FAQPage schema rules,
[content.md](content.md) for answer-first copy.

## 4. `/llms.txt` content spec

A hand-authored `/llms.txt` on the **public host** for ChatGPT, Claude,
and Perplexity. Google Search ignores this file.

### Implementation

- **Next.js static sites:** route handler at `app/llms.txt/route.ts`
  rendered from the typed `content/` files (same source of truth as
  pages). Add `export const dynamic = "force-static"` to keep the site
  fully static.
- **WordPress:** see [platforms.md](platforms.md).
- **Other stacks:** a hosted text file at the web root.

### Required content

- Business name, address, phone (NAP)
- Hours of operation
- Services / products offered
- Primary money-action URL (booking, call, directions, etc.)
- FAQ answers (same text as the visible FAQ and FAQPage JSON-LD)
- Public page list including `/faq` when it exists

### Host rules

- Every URL in the file must use the **public production host**.
- A preview host (`*.vercel.app`, `*.pantheonsite.io`, etc.) in the file
  is worse than leaving it off until cutover — it teaches answer engines
  the wrong address.
- **Cutover gate:** when the public domain goes live, confirm the preview
  host is gone from `/llms.txt`, canonicals, sitemap, and JSON-LD.

See also: `aeo-audit audit` checks `/llms.txt` presence and host leaks;
[platforms.md](platforms.md) for per-stack llms.txt notes.

## 5. LocalBusiness JSON-LD (local/service businesses)

For local and service-area businesses (salon, tree service, auto shop,
liquor store, church, contractor, etc.), ship `LocalBusiness` or a real
subtype on the homepage.

### Subtypes (use the most specific that fits)

`LiquorStore`, `HairSalon`, `Church`, `AutoRepair`,
`GeneralContractor`, `HomeAndConstructionBusiness`,
`ProfessionalService`, `LocalBusiness` (fallback).

There is no clean `PetGroomer` type — use `LocalBusiness` or
`ProfessionalService`.

### Required properties

- `name`, `telephone`, `address`, `geo` (lat/lng)
- `openingHoursSpecification` (hours)
- `areaServed` — service-area towns
- `hasOfferCatalog` — from the services content
- `image` — a real photo
- `sameAs` — profiles the business actually uses (booking platform,
  Google Maps, real social profiles). Do not pad with dead or irrelevant
  links.

### Rules

- Never emit `offers.price` unless that price is published on the page.
  Booking-tool pricing stays in the booking tool.
- Never emit `aggregateRating` from copied reviews. Testimonials stay
  visible text only.
- Team-led verticals (salon, medspa) may also emit `Person` for each
  bookable staff member (`name`, `jobTitle`, `worksFor`, `image` when a
  real photo exists).
- NAP in schema must be identical to the Google Business Profile.
- Multi-location caution: if "sister" stores are different ownership or
  different domains, scope NAP + schema to **one** store.

See also: [schema.md](schema.md) for general schema rules and
validation workflow.

## 6. Static HTML requirement

Everything is server-rendered static HTML — facts must never be JS-only.
Answer engines and Google cannot reliably execute client-side JavaScript
to discover business facts.

---

## Validation

After build, run:

```bash
aeo-audit audit SITE --write    # checks robots, llms.txt, schema, snippet eligibility
aeo-audit schema SITE --write   # JSON-LD review + validator URLs
aeo-audit metas SITE --write    # title + meta description audit
```

Then open both official validators (Schema Markup Validator + Google Rich
Results Test) on the homepage and `/faq`. See [schema.md](schema.md)
for the full validator workflow.
