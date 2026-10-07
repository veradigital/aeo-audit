---
name: aeo-audit
description: Audit one public site for answer engines. Use when the user says AEO, GEO, AI visibility, llms.txt, schema, meta descriptions, or asks whether a URL can be cited. Runs pass/warn/fail checks. Does not publish pages or score the site out of 100.
---

# Answer-engine audit

Check one named site. Do not crawl a list of unrelated sites unless the user named each one.

## Before any edit

1. Read the playbook that matches the task. Start with `playbooks/audit.md`. Titles and metas: `playbooks/meta-descriptions.md` and `playbooks/titles.md`. Schema: `playbooks/schema.md`. Page copy: `playbooks/content.md`. Buyer prompts: `playbooks/prompts.md`.
2. Run the matching command and keep the output. A domain works when the site is not in `inventory/sites.toml`:

```bash
aeo-audit audit https://example.com --entity "Product name"
aeo-audit metas example --write
aeo-audit schema example --write
```

3. Treat each line as pass, warn, or fail. Do not average them into a score. Do not invent impressions, citations, or a percentage.

## Optional keys

The on-page commands run with no key. If a key in `.env` is set, run the matching command and keep the result. If it is unset, skip that command and say the check was skipped. Never print a key value. Never commit `.env` or paste a key into the report.

| If this is set | Run | What improves |
| --- | --- | --- |
| `PSI_API_KEY` | `aeo-audit recommend`, or `aeo-fleet psi` when that CLI is installed | Mobile and desktop speed, and a speed note on the recommendation list |
| `GSC_SERVICE_ACCOUNT_JSON` or `GSC_SERVICE_ACCOUNT_FILE` | `aeo-fleet gsc` | Queries, clicks, click-through rate, position, and low-click pages |
| `GBP_SERVICE_ACCOUNT_JSON`, `GBP_SERVICE_ACCOUNT_FILE`, or `GBP_OAUTH_TOKEN` | `aeo-fleet gbp` | Listing views, clicks, calls, direction requests, and reviews |
| Any of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY` | `aeo-fleet ai-check` | Whether each engine names the company and cites the site URL. One key is enough. |
| `GOOGLE_PLACES_API_KEY` | `aeo-fleet competitor` | Nearby places. The public competitor crawl still runs with no key. |

Details are in the README under API keys.

## What a failure means

- Answer crawlers blocked, or `noindex` / `nosnippet` / `max-snippet:0` on a page that should be quoted.
- `/llms.txt` names a staging host or dumps the whole sitemap. A missing file is only a warning. Google Search ignores `llms.txt`.
- Organization, product, and FAQ schema disagree with the visible page.
- The public HTML or JSON-LD still contains a platform hostname (`pantheonsite.io`, `wpenginepowered.com`, and the other hosts the audit lists).
- The phone, name, or product differs between the page, JSON-LD, and `llms.txt`.

## After a fix

Re-run the same command with `--write` and diff `reports/<slug>/`. Schema is not done until the Schema Markup Validator and Google Rich Results Test have been opened on the homepage, the money page, and one article. Paste the detected types into the report. Extraction alone is not confirmation.

Do not create a new URL per question. Add the answer to a page that already exists.

Do not commit `inventory/sites.toml`, `.env`, or `reports/`.
