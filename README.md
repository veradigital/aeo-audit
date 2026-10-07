# aeo-audit

An answer-engine audit checks whether a public page can be fetched, quoted, and attributed to the right organization. It reports each check as pass, warn, or fail. It does not produce a 0–100 score, and it does not publish pages for you.

The checks that usual SEO crawlers skip: answer crawlers versus training crawlers, snippet blocks (`noindex`, `nosnippet`, `max-snippet:0`), a useful `/llms.txt` versus a host dump, entity consistency across the page, JSON-LD, and that file, and hostnames that leak a staging platform.

## Install

Requires Python 3.11 or newer. No API key is required for the core checks.

```bash
pip install git+https://github.com/veradigital/aeo-audit.git
```

From a checkout, so later edits apply immediately:

```bash
pip install -e .
aeo-audit init
```

`init` writes `inventory/sites.toml` in the current directory (or in `AEO_DATA_DIR` when that variable is set). Reports go to `reports/<slug>/` in that same directory. The example inventory is `inventory/sites.example.toml`.

## Commands

Name one site. A domain works when it is not in the inventory: `aeo-audit audit https://example.com --entity "Example Widget"`.

```bash
aeo-audit list
aeo-audit audit example --write
aeo-audit crawl example --write
aeo-audit metas example --write
aeo-audit metas example --proposed drafts.csv --write
aeo-audit schema example --write
aeo-audit content example
aeo-audit consistency example
aeo-audit keyphrase example
aeo-audit prompts example
aeo-audit recommend example --write
```

Exit code `2` means at least one check failed. Exit code `0` means nothing failed. Warnings do not fail the command.

How to apply a failure is in `playbooks/`. Start with [playbooks/audit.md](playbooks/audit.md). The other playbooks cover titles, meta descriptions, schema, content, and prompts.

## API keys

The on-page commands run with no key. Add a key and the matching check turns on. Leave it unset and that check is skipped. Use your own values. Never commit them, and never paste a key into a report or a chat.

Put them in `.env` in the data directory (the folder that contains `inventory/`, or `AEO_DATA_DIR`). The file is loaded once, at startup. A variable already set in the shell wins. `.env` is gitignored.

`recommend` in this package reads `PSI_API_KEY`. The other commands below are `aeo-fleet`. Agents should run a command when its key is set, and skip it when the key is absent.

| If you set | The command that improves | What you gain |
| --- | --- | --- |
| `PSI_API_KEY` | `recommend`, and `aeo-fleet psi` | PageSpeed scores and Core Web Vitals. The free quota works with no key. A key raises that quota, and `recommend` adds a mobile speed note. |
| `GSC_SERVICE_ACCOUNT_JSON` or `GSC_SERVICE_ACCOUNT_FILE` | `aeo-fleet gsc` | Real queries, clicks, click-through rate, average position, and pages that get impressions but few clicks. |
| `GBP_SERVICE_ACCOUNT_JSON`, `GBP_SERVICE_ACCOUNT_FILE`, or `GBP_OAUTH_TOKEN` | `aeo-fleet gbp` | Listing views, website clicks, calls, direction requests, and review stats. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `PERPLEXITY_API_KEY` | `aeo-fleet ai-check` | The buyer prompts are sent to each engine that has a key. The report records whether the company was named and whether the site URL was cited. One key is enough. |
| `GOOGLE_PLACES_API_KEY` | `aeo-fleet competitor` | Nearby places for the site's vertical and city. Crawling a competitor's public pages still works with no key. |

## Agents

Humans run the commands above. Agents should follow [skills/aeo-audit/SKILL.md](skills/aeo-audit/SKILL.md) and the playbooks. Do not paste a playbook into a prompt. Read the file.

This repo installs that skill for Cursor, Claude Code, and Codex via symlinks:

- `.cursor/skills/aeo-audit`
- `.claude/skills/aeo-audit`
- `.codex/skills/aeo-audit`

All three point at `skills/aeo-audit`, so one edit updates every tool. [AGENTS.md](AGENTS.md) is the short entry point.

## FAQ

### What is an answer-engine audit?

It is a check that a public URL can be retrieved by answer engines, quoted without a snippet block, and tied to one organization. Search rank is a separate question. This tool does not estimate traffic or keyword volume.

### Why is there no score out of 100?

A single number hides a failed `noindex` behind a long list of passes. Each check stays pass, warn, or fail, with the evidence and the fix on that line.

### Which crawlers matter?

Answer crawlers (the ones that fetch a page to cite it) are not the same as training crawlers. Blocking a training crawler can be a pass. Blocking every crawler with `Disallow: /` fails the answer-crawler check. The bot lists are in the audit output.

### Does Google use llms.txt?

No. Google Search ignores `llms.txt`. A missing file is a warning because other answer engines use a short brief. A bad file is a failure: a staging hostname, or a dump of every URL, teaches the model the wrong host. Hand-write the brief. Do not publish a plugin's default sitemap dump.

### What makes a page quotable?

The page is indexable, the robots meta tag does not set `nosnippet` or `max-snippet:0`, and the first screen has a direct answer. Put frequently asked questions on a page that already ranks. Do not create a new URL for every question.

### Why check the same facts in four places?

Answer engines mix the visible page, JSON-LD, `llms.txt`, and a business profile. If the phone, name, or product differs, they may cite the wrong one or skip the business. The consistency command compares those copies.

### What is a host leak?

A public page or JSON-LD `@id` that still uses a platform hostname, such as `pantheonsite.io` or `wpenginepowered.com`, splits the entity. Fix the canonical host, then re-run `aeo-audit schema`.

### Do I need an API key?

No. The on-page audit, drafts, and crawl run with none. Add a key from [API keys](#api-keys) when you want that extra check. Leave the others unset.

### Can I audit a site without an inventory file?

Yes. Pass a domain or URL. `--entity` sets the product name used by the title and schema checks. `init` is only needed when you want to save prompts, key pages, and spelling rules.

### What does this leave out?

The commands in this repo fetch the public page and write a report. Apply the fixes in the CMS you already use, then run the same command again and diff the report. Search Console, the business profile, answer engines, and Places are the fleet commands in the [API keys](#api-keys) table.

## License

[MIT](LICENSE). Copyright 2026 Nathan Herring.
