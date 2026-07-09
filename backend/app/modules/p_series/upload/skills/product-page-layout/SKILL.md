# Skill — Product-page description layout (WooCommerce HTML)

version: p-product-page-layout-v1

## Goal

Turn a K product's structured data (lead copy, benefit bullets, specs, materials,
dimensions, usage, variants) into the **`description_html`** block that n8n drops
into the WooCommerce product description. Two non-negotiables:

1. **Consistency** — every product, regardless of category, follows the **same
   section skeleton in the same order**, using the **same semantic tags and class
   names**, so every product page on the site reads as one system.
2. **Category-appropriate emphasis** — which optional sections appear, and what
   goes in the category block, adapts to the product's category.

Grounded in Baymard Institute product-page UX research and NN/g ecommerce product
page guidelines (complete, scannable info; benefits categorized; technical
products need specs + compatibility + installation).

## Hard rules (do not violate)

- **No inline styles.** Emit semantic HTML with stable class names only
  (`kp-desc`, `kp-lead`, `kp-benefits`, `kp-specs`, …). The WordPress theme owns
  visual styling — that is what keeps every product visually identical.
- **No prices, no stock/availability, no shipping promises in the description
  body.** Those live in WooCommerce's structured fields and the GMC feed. Putting
  them in the description is the #1 cause of **feed ↔ landing-page mismatch →
  Google Merchant Center "misrepresentation" disapproval**. The description is
  marketing prose + specs only. See the packaged schema (`upload_package.py`);
  price/availability flow through structured fields, never prose.
- **No invented facts.** Use only supplied product data (bullets,
  marketing_copy, attributes, dimensions, materials, variants). If a section has
  no data, **omit the section** — never fabricate specs, certifications, or
  claims.
- **No medical / legal / absolute claims** (esp. supplements, beauty): no "cures",
  "guaranteed", "FDA approved" unless supplied and verifiable.
- **Escape all product text** (it may contain `<`, `&`). Output must be valid,
  self-closing-safe HTML.
- **Target-market language** — write in the product's target locale (default
  en-US); do not emit the Chinese review copy.

## Universal skeleton (ALWAYS this order)

```html
<div class="kp-desc">
  <p class="kp-lead">…marketing_copy lead paragraph (the hook)…</p>

  <section class="kp-benefits">
    <h3>Why you'll like it</h3>
    <ul>
      <li>…benefit bullet (must-have benefits first)…</li>
    </ul>
  </section>

  <!-- CATEGORY BLOCK inserted here (see below) -->

  <section class="kp-specs">
    <h3>Specifications</h3>
    <table><tbody>
      <tr><th>Material</th><td>…</td></tr>
      <tr><th>Dimensions</th><td>…</td></tr>
    </tbody></table>
  </section>

  <section class="kp-box">
    <h3>What's in the box</h3>
    <ul><li>…package_includes…</li></ul>
  </section>
</div>
```

Rules for the skeleton:
- `kp-lead` = `marketing_copy` paragraph. If absent, use `short_description_en`.
- `kp-benefits` = the copy `bullets`, benefit-led, ranked (must-have → nice-to-have).
- `kp-specs` = a `<table>` from the product's attributes / materials / dimensions /
  weight. Omit the whole section if there are zero specs.
- `kp-box` = `package_includes`. Omit if empty.
- Omit any section whose data is empty. Never render an empty `<ul>`/`<table>`.

## Category block (choose ONE by product category)

Insert exactly one category block between benefits and specs. Pick by the
product's category / `google_product_category` / product_type; fall back to
`general`.

- **apparel / fashion** → `<section class="kp-fit">`: size & fit table
  (size → measurements), model measurements if supplied, material & care line.
  Add a "Size & fit" heading. (Apparel shoppers fail most on fit uncertainty.)
- **electronics / tech** → `<section class="kp-compat">`: compatibility list
  ("Works with …"), key tech specs surfaced as scannable icon-free bullet pairs
  (Feature → plain-English benefit), in-the-box already covered by kp-box.
- **home / furniture / decor** → `<section class="kp-dimensions">`: dimensions
  with context (assembled size, weight capacity), materials, **care
  instructions**, assembly note.
- **kitchen / food / grocery** → `<section class="kp-usage">`: capacity/servings,
  usage instructions, cleaning/care, materials (food-safe note only if supplied).
- **supplements / health** → `<section class="kp-usage">`: suggested use,
  ingredients/materials, storage. **No health/medical claims** beyond supplied
  verifiable text.
- **beauty / personal care** → `<section class="kp-usage">`: how to use, key
  ingredients, skin/hair type, cautions.
- **tools / hardware / industrial** (e.g. pumps, fittings) →
  `<section class="kp-compat">`: technical spec table emphasis, **compatibility**
  ("fits …"), **installation notes**, materials, certifications (only if supplied).
- **general** (default) → no extra block; skeleton only.

## Variants

If the product has variants, do **not** hand-render each variant's price/image in
the description (WooCommerce variations handle that). Optionally add a single
`<section class="kp-variants">` listing available options in prose
("Available in: Black, Navy · S–XXL") for scannability — options only, never
prices.

## Output contract

Return an object:
```json
{
  "description_html": "<div class=\"kp-desc\">…</div>",
  "layout_skill_version": "p-product-page-layout-v1",
  "category_block": "kp-compat",         // which block was chosen
  "sections_emitted": ["kp-lead","kp-benefits","kp-compat","kp-specs","kp-box"],
  "omitted_for_missing_data": ["kp-box"] // transparency for review
}
```

The operator reviews `description_html` before the product is dispatched; the
`sections_emitted` / `omitted_for_missing_data` make gaps explicit instead of
silently producing a thin page.
