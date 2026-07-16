# PDP overhaul pipeline contracts

This file freezes the two data contracts shared by the pipeline code and the
art-direction producer. Missing supplier facts are omitted; neither contract
permits a generated fallback value.

## `structured_specs_json` v1.0

```json
{
  "schema_version": "1.0",
  "source": {
    "platform": "1688",
    "offer_id": "123456",
    "url": "https://detail.1688.com/offer/123456.html"
  },
  "lumens": {
    "value": 800,
    "unit": "lm",
    "raw_value": "800 lm",
    "source_label": "光通量"
  },
  "color_temperature_k": {
    "value": {"min": 2700, "max": 6500},
    "unit": "K",
    "raw_value": "2700-6500",
    "source_label": "色温(K)"
  },
  "dimensions": {
    "length": {
      "value": 12,
      "unit": "cm",
      "raw_value": "120×80×50 mm",
      "source_label": "产品尺寸"
    },
    "width": {
      "value": 8,
      "unit": "cm",
      "raw_value": "120×80×50 mm",
      "source_label": "产品尺寸"
    },
    "height": {
      "value": 5,
      "unit": "cm",
      "raw_value": "120×80×50 mm",
      "source_label": "产品尺寸"
    },
    "unit": "cm",
    "raw_value": "120×80×50 mm",
    "source_label": "产品尺寸"
  },
  "additional_specs": [
    {
      "key": "supplier_attribute_12b056a932",
      "label": "输入电压",
      "value": "5V",
      "raw_value": "5V"
    }
  ]
}
```

Standard keys are `lumens`, `color_temperature_k`, `battery_type`,
`battery_capacity_mah`, `charge_time_h`, `runtime_h`, `ip_rating`,
`dimensions`, `weight`, `material`, `mount_type`, and `certifications`.
Canonical units are `lm`, `K`, `mAh`, `h`, `cm`, and `kg`. A scalar evidence
leaf is `{value, unit?, raw_value, source_label}`. `value` may be a number, a
string, a list of scalar options, or a `{min,max}` range. Identity fields such as
brand, manufacturer, and seller are discarded. Unmapped supplier facts use
`additional_specs`.

## `overlay` k-info-overlay-v1

Only image roles `feature_callout`, `dimension`, and `spec` use this contract.
Coordinates are normalized to the closed range 0..1. A main image never accepts
an overlay; both enqueue and media-storage boundaries discard one if supplied.

```json
{
  "schema_version": "k-info-overlay-v1",
  "role": "feature_callout",
  "items": [
    {
      "type": "callout",
      "source_field": "ip_rating",
      "anchor": {"x": 0.46, "y": 0.42},
      "text_anchor": {"x": 0.76, "y": 0.22},
      "leader_direction": "right"
    },
    {
      "type": "dimension",
      "source_field": "dimensions.height",
      "line": {
        "start": {"x": 0.18, "y": 0.16},
        "end": {"x": 0.18, "y": 0.84}
      },
      "text_anchor": {"x": 0.12, "y": 0.50}
    }
  ]
}
```

`source_field` is required and must be one of `lumens`,
`color_temperature_k`, `battery_type`, `battery_capacity_mah`, `charge_time_h`,
`runtime_h`, `ip_rating`, `dimensions.length`, `dimensions.width`,
`dimensions.height`, `weight`, `material`, `mount_type`, or `certifications`.
There is deliberately no free-form `label`, `text`, or numeric-value field:
display labels are fixed server-side. Before resolving a field, the K worker
requires `structured_specs_json.schema_version == "1.0"`,
`source.platform == "1688"`, and non-empty `raw_value` plus `source_label` on
the referenced evidence leaf. Missing/unverified paths skip that annotation.
Invalid or failed overlays leave the clean base image untouched and do not fail
rendering or publication. Overlay composition happens in the K image worker,
before the rendered media asset is stored; P only publishes that finished asset.

## Woo structured-data adapter

The upload workflow writes the verified properties to visible Woo product
attributes and to `_kp_additional_property`. Deploy
`backend/app/modules/p_series/wordpress/kp-product-structured-data.php` as a
WordPress must-use plugin so Woo's native Product graph receives
`additionalProperty`. The adapter never writes `aggregateRating` or `review`;
Woo retains ownership of those fields and emits them only from stored,
approved customer reviews.

The v4 workflow rejects older upload-package versions before touching specs.
It records its owned attribute names in `_kp_managed_attribute_names`; updates
remove/rewrite only those names and preserve manual or variation attributes.
An empty verified-spec set therefore clears stale pipeline claims without
resetting the product's entire Additional information table.

Woo identity is independent of the new public SKU. The package supplies the
last successful Woo product ID when one exists and snapshots the pre-allocation
SKU for the first migration lookup. n8n queries that ID/legacy SKU and performs
a PUT whose body carries the new category-issued SKU, so an existing ASIN-keyed
product is rekeyed rather than duplicated.

## Release checklist

1. Apply Alembic through `20260716_03_structured_specs` (migrations are not run
   automatically by this change).
2. Rebuild/redeploy the backend image; `backend/Dockerfile` installs
   `fonts-noto-cjk` for supplier values containing CJK characters.
3. Re-import `p_upload_workflow.json` into n8n.
4. Install `kp-product-structured-data.php` as an MU plugin and verify a live
   Product graph contains `brand.name = Barong Yekhna`, verified
   `additionalProperty`, and review fields only when Woo has approved reviews.
5. Re-upload a known legacy ASIN-keyed product and confirm Woo updates the same
   numeric product ID rather than creating a second product.
