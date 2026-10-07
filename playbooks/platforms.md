# Platform notes

The audit is stack-agnostic. Apply uses whatever door the site already has.

## WordPress + Yoast

**Titles / meta / schema:** Yoast per-page. Organization in Search Appearance. Add `SoftwareApplication` / `FAQPage` with a small custom snippet or Yoast schema blocks if the default graph is only WebPage/WebSite/Breadcrumb. After any schema change, run `aeo-audit schema SITE --write` and confirm in [Schema Markup Validator](https://validator.schema.org/) (0 errors) and [Google Rich Results Test](https://search.google.com/test/rich-results) (detected types match the page). See [schema.md](schema.md).

**Host leaks:** Yoast will emit `https://live-{site}.pantheonsite.io/#website` when that host is what WordPress believes is home, or when the graph was generated on a Pantheon URL. Fix `home` / `siteurl` to the public domain, then save Yoast settings on **Live** (not Dev).

**Search Console:** Settings → Search generative AI should stay on include. Then check Performance → Generative AI. The report shows impressions by page, country, and device. It does not show queries, clicks, or CTR. `nosnippet` and `max-snippet:0` block both AI Overviews and the normal snippet.

**llms.txt:** Useful for ChatGPT, Perplexity, and Claude. Google Search ignores it. Yoast 25.3+ writes a physical file and refreshes weekly. On Pantheon Live the codebase is read-only, so the file is often a Dev leftover (Dev permalinks, duplicate dump, pattern categories). Do this instead:

1. Hand-author `reports/<slug>/llms.proposed.txt`.
2. Either: disable Yoast llms.txt and serve the hand file at `/llms.txt` (uploads + webroot symlink, or a tiny MU plugin `template_redirect`), **or** fix Yoast generation on Live using `wpseo_llmstxt_filesystem_path` → uploads + symlink, then heavily curate which content Yoast includes.
3. Prefer the hand file. Yoast’s default list is a sitemap dump, not a brief.

**FAQ:** A real page (`/faq/` or `/services/#faq`). On a post, one Kadence accordion with `faqSchema: true`. The heading is “Frequently Asked Questions About [topic]”. Schema is printed only when `parse_blocks` sees that accordion and its panes. Confirm `FAQPage` on the public URL after every content write.

**WP-CLI:** Confirm the public host before changing schema.

```
wp option get home
wp option get siteurl
wp option get blogdescription
```

## Next.js / static

`app/llms.txt/route.ts` (or `public/llms.txt`), `robots.ts` with named AI allows, JSON-LD in the layout, FAQ route. Generate llms from the same content objects the pages use.

## Webflow / other hosted

Export or embed: custom code for JSON-LD + a hosted `llms.txt` if the host allows a root text file. If it does not, put the brief at a stable URL and link it from robots and the homepage.

## Do not

- Stand up a parallel Next.js marketing site “for AEO” unless asked.
- Copy `aggregateRating`.
- Point llms.txt at Dev/Test.
