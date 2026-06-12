# K10C Mock Adapter Module Report

Status: K10C Python skeleton only.

Date: 2026-06-12.

# 1. K10C Goal

K10C creates a module-local DeepSeek mock adapter skeleton for K-series product
knowledge unit output. It defines constants, dataclasses, helper signatures,
empty draft result builders, unit payload draft placeholders, field diff draft
metadata, and lightweight local shape validation.

K10C does not implement AI behavior, text parsing, provider calls, runtime
wiring, service integration, routing, DB writes, or review approval.

# 2. Created Python File

- `backend/app/modules/k_series/product_knowledge/k10_mock_adapter.py`

# 3. Why This Is A Mock Skeleton

The module returns deterministic local dictionaries only. It preserves source
metadata, emits draft review metadata, and leaves unit values empty unless
explicit local `provided_values` are passed to a placeholder draft helper.

The module does not call DeepSeek, does not call any other live provider, does
not read credentials or env, and does not parse free text. It is a future
implementation surface, not a live adapter.

# 4. Boundary Report

- DeepSeek live connected: no.
- Env read: no.
- Live services connected: no.
- `service.py` modified: no.
- `schemas.py` modified: no.
- `router.py` modified: no.
- `models.py` modified: no.
- `__init__.py` modified: no.
- `unit_conversion.py` modified: no.
- `unit_payloads.py` modified: no.
- Router registered: no.
- Frontend written: no.
- Tests written: no.
- Migration created: no.

# 5. Supported Mock Output Sections

- `canonical_product_fields`
- `unit_payloads`
- `dimensions_json`
- `package_dimensions_json`
- `weight_json`
- `package_weight_json`
- `ai_warnings_json`
- `field_diff_json`
- `missing_field_hints`

# 6. AI No-Guessing Policy

AI output must not guess missing product facts, dimensions, weights, package
dimensions, net/gross weight distinction, or product/package distinction.
Missing or unknown values must not become `0`. Unsupported, missing, invalid,
or ambiguous unit facts must remain draft review metadata with warning or error
codes.

# 7. Draft / Needs Review Policy

Mock AI output is limited to `draft` or `needs_review`. K10C uses
`needs_review` by default. The module never emits reviewed, approved,
publish-ready, shipping-ready, or reviewer-corrected output.

# 8. K10D Test Follow-Up

K10D should add owner-approved unit tests for:

- `build_mock_input` dictionary shape and copy behavior.
- `build_empty_mock_result` required fields and no live provider fields.
- `build_mock_structured_output` deterministic draft behavior.
- `build_unit_payload_draft` missing value/unit behavior.
- `build_field_diff_draft` review-only metadata.
- `validate_mock_result_shape` allowed statuses, required fields, and forbidden
  provider output keys.
- `list_supported_output_sections` exact section list.

# 9. Live Adapter Blocker

K10 live adapter remains blocked until C14/C09 provider rules and explicit owner
approval. K10C does not approve runtime integration, live DeepSeek calls,
provider credentials, backend service integration, API exposure, n8n
consumption, P-series consumption, WooCommerce draft behavior, or frontend
activation.
