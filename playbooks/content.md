# Content updates that increase AEO

Use this on **existing** pages and posts. New URLs are optional (P2).

## Answer-first block

Put this above the fold on every page that should be cited. 40–80 words. No teaser, no “in this article.”

```
[Thing] is [one-sentence definition].
It is for [buyer] who need [outcome].
It works with [compatibility].
It is not [common confusion].
Get started: [money URL].
```

Then the rest of the article.

## FAQ on the page

6–10 questions the buyer actually types, on a page that already ranks. Answers: 1–3 factual sentences. Same text goes into one FAQPage block and `/llms.txt`.

The visible heading is “Frequently Asked Questions About [topic]”, even when the source doc says “FAQ:”.

A paragraph that ends with a colon and introduces a list uses a short bottom margin (`spacing|20`) so the list sits close to that line. Numbered versus bullet lists follow the source doc.

Google does not use FAQPage, special AI markup, or `llms.txt` to decide AI Overviews. The page still needs to be indexed, snippet-eligible, and included under Search Console → Settings → Search generative AI. Do not create a new URL for each People Also Ask or fan-out question.

Good: “Does Example Widget work offline?”
Bad: “Why choose us?” / “What makes us different?”

## Comparison posts

The highest-citation B2B pattern: “X vs Y” or “N reasons not to use Y.”

- Public, complete answers. Do not gate the remaining reasons behind a form.
- One comparison table in HTML (not only an image).
- Metrics consistent with the product page.
- Old product names (MIT, internal codes) labeled as former / now called {current}.

A video-first index can be retrieved and still not quoted. If the engine cannot lift a 40–80 word answer from the first screen, it will recommend someone else.

## Blog cadence (P2)

One citeable piece beats four lifestyle posts.

Rotate: comparison · definition · industry proof · how-to that names the product in the first sentence.

Update the 3–5 URLs already in the sitemap that match buyer prompts before writing net-new.

## Source document onto an existing post

Match the source. Do not rewrite it in pieces.

- Words, bold, italics, and list type come from the source. Numbered lists stay numbered. Bullet lists stay bullets. Render the document and use the marker it shows. Do not invent bold on a label the source does not bold.
- Keep the page’s existing headings, separators, and related links.
- The visible FAQ heading is “Frequently Asked Questions About [topic]”, even when the source says “FAQ:”.
- Meta is 120–156 characters. The keyphrase is a phrase already in the title. Do not paste a long suggested meta from the source.
- Do not publish production notes, HowTo schema, or a “Q:” prefix on questions.
- After the write, confirm the public page has one `FAQPage` and the same questions as the visible FAQ.

If the slug changes, add a 301 from the old URL to the new one and update links on other pages.

## Claim lock

Keep a 10-line fact block in `reports/<slug>/facts.md` (NAP, metrics, compatibility, money URL). Every edit is checked against it. Homepage and article metrics must match.
