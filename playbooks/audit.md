# Audit playbook (any stack)

Name the site. Run HTTP first. Then metas. Then entity/content. Then live answer-engine prompts. Then a prioritized plan. Do not rebuild the site.

```
aeo-audit audit SITE --write
aeo-audit schema SITE --write
aeo-audit metas SITE --write
aeo-audit prompts SITE
```

Then open both official validators on home, the product/money page, and one article — see [schema.md](schema.md). CLI extraction is not confirmation.

## Layer 1 — Technical eligibility (CLI)

The CLI already fails these. Confirm the evidence, do not re-litigate a PASS.

| Gate | Fail looks like | Why it matters |
| --- | --- | --- |
| Homepage 200 on the public host | 4xx/5xx, or apex ≠ www with no 301 | No page, no citation |
| Title + meta name the current offer | Services-era title on a product homepage. Run `aeo-audit metas SITE --write` for the full per-page check ([meta-descriptions.md](meta-descriptions.md)) | Models quote title/meta first |
| One H1 | Slider with 3 H1s | No single quotable claim |
| robots.txt + sitemap | Missing, or sitemap 500 to unknown UAs | Discovery gap |
| Answer crawlers not blocked | `Disallow: /` on OAI-SearchBot, ChatGPT-User, Claude-SearchBot, Claude-User, PerplexityBot, Perplexity-User, or on `User-agent: *` | Those engines cannot fetch the page. A block on GPTBot, ClaudeBot, or Google-Extended is training only. It does not remove AI Overviews. `User-agent: *` with `Allow: /` is enough — do not demand named Allow lines |
| Index and snippet eligible | `noindex`, `none`, `nosnippet`, or `max-snippet:0` on the homepage or a key page | `noindex` keeps the URL out of Google. `nosnippet` and `max-snippet:0` block AI Overviews, AI Mode, and the normal snippet |
| `/llms.txt` | Missing file is a warning. Yoast junk, staging hosts, or a duplicate file is a failure | For ChatGPT, Perplexity, and Claude. Google Search ignores the file. A bad file still teaches the wrong host to the engines that read it |
| Visible FAQ | Questions only in a new URL per query, or two FAQPage blocks | Put buyer questions on pages that already rank. FAQPage is not how a page gets into AI Overviews |
| Useful JSON-LD | Only WebPage/WebSite/Breadcrumb | Names the company and product for rich results. Extra “AI schema” does not help Google Search ([schema.md](schema.md)) |
| No host leaks | `pantheonsite.io`, `wpenginepowered.com`, etc. in HTML/schema/llms | Entity splits; citations go to the platform URL |

## Layer 2 — Entity + content (agent)

Read the homepage, money page, about, 3–5 best articles. Write down:

1. **Canonical names** — legal name, product name, aliases to retire (old product codes, internal nicknames).
2. **Facts that must stay identical** everywhere: NAP, claims/metrics, compatibility, money URL.
3. **Claim drift** — homepage says 30%, article says 15–30%. Pick one approved set. Do not invent a third.
4. **Quotable pages** — comparisons, definitions, how-tos. Are the answers public, or gated after paragraph 2?
5. **Third-party sameAs** — LinkedIn, SAP Store, GBP, YouTube, Crunchbase. Missing sameAs = weaker entity.

## Layer 3 — Observed answers

Run the inventory prompts verbatim in ChatGPT, Claude, Gemini, Perplexity. Same day. Fill `reports/<slug>/ai-visibility.md`:

| Engine | Prompt # | Mentioned? | Cited URL? | Facts correct? | Who else was recommended? |
| --- | --- | --- | --- | --- | --- |

Mention rate and citation rate are the score. Do not invent a composite 0–100.

## Human brief (`reports/<slug>/BRIEF.md`)

Write this even if a CLI audit file already exists. Two sections only:

1. **What the site already does well** — real assets to keep (pages, proof, sitemap, off-site identity). Be specific. Do not pad.
2. **What to do (impact order)** — one numbered table: `# / Do / Why (impact)`. Highest citation-surface × fixability first. No P0/P1/P2 labels in the brief; order is the priority.

Point the dated CLI audit at `BRIEF.md` at the top.

Apply with [apply.md](apply.md). Re-run the CLI after.

## How often

- Weekly: review public Google and answer-engine guidance, and update this playbook when a practice stops working.
- After each launch or in-place apply: run `audit` and `schema`, then open both validators.
- Monthly: Search Console generative AI report (impressions by page, country, and device) and the same buyer prompts.
- Quarterly: NAP, `sameAs`, and FAQ facts still match the live pages.
