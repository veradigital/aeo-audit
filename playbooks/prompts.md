# Observed-answer pass

Use the site’s `prompts` from `inventory/sites.toml`. Do not improvise replacements during a baseline — add extra prompts in a later dated file.

## How to run

Same calendar day, logged-out / no custom GPT instructions if possible.

1. Paste prompt 1. Save the full answer + any cited URLs.
2. Repeat for every prompt × ChatGPT, Claude, Gemini, Perplexity.
3. Score the grid in `reports/<slug>/ai-visibility.md`.

Mention = brand or product name appears.
Citation = a URL on the site’s public host.
Accuracy = facts match `reports/<slug>/facts.md`.

## Interpreting

| Pattern | Meaning |
| --- | --- |
| Never mentioned | Entity is unresolved. Fix leaks, names, and snippet eligibility first. `/llms.txt` helps ChatGPT, Perplexity, and Claude. Google Search ignores it. |
| Mentioned, never cited | They know the name from training/third parties. Give them citeable public answers. |
| Cited, facts wrong | Drift between title/meta/llms/pages. Lock facts. |
| Competitor always wins the same prompt | That competitor has a cleaner comparison/definition page. Write the public answer they are using. |

Re-run the same prompts after P0/P1. Append, do not overwrite.
