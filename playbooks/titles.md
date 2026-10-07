# Title tag patterns for local/service businesses

Supplements [meta-descriptions.md](meta-descriptions.md) (which covers
length, uniqueness, brand suffix, focus phrase, and spelling rules) with
**local-intent patterns** for service-area and local businesses.

These patterns apply to any local business site audited with `aeo-audit metas`.

---

## Local-intent title formula

```
[Vertical / Service] in [City], [ST] | [Brand Name]
```

Examples:

- `Liquor Store in Springfield, IL | Example Liquors`
- `Tree Service in Springfield, IL | Example Tree Care`
- `Hair Salon in Springfield, IL | Example Salon`
- `Auto Repair in Springfield, IL | Example Auto`
- `Pet Grooming in Springfield, IL | Example Grooming`

### Rules

- **Homepage and service pages** must include city + state + vertical.
  Interior pages (About, FAQ, Contact) include the brand but may omit
  the geo if the title already names a specific topic.
- **Service-area towns** in service-page titles when the page is
  geo-specific (e.g. "Storm Damage Tree Removal in Springfield, IL").
- Brand goes **after** the pipe separator. The focus topic/geo comes
  first for keyword prominence.
- Keep within the 30–60 character target range per
  [meta-descriptions.md](meta-descriptions.md). Trim the state
  abbreviation or use a shorter brand form if needed.
- Match the `<title>` to the H1's intent but do not make them
  word-for-word identical (the title is for SERPs; the H1 is for
  the visitor).

### Per-page metadata object (Next.js)

Use the Next.js `metadata` export (or `generateMetadata`) with local
intent:

```ts
export const metadata: Metadata = {
  title: "Liquor Store in Springfield, IL | Example Liquors",
  description: "70+ years of wine, spirits, and beer…",
};
```

### When NOT to use local-intent titles

- National / SaaS / B2B brands that sell globally — use the product +
  brand pattern from [meta-descriptions.md](meta-descriptions.md).
- Blog posts / articles — use the article headline + brand.

See also: `aeo-audit metas SITE --write` for automated title tag
auditing across all pages.
