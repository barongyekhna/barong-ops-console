# K10C Review Checklist

Status: K10C local review checklist.

Date: 2026-06-12.

# Scope

- [ ] Only `backend/app/modules/k_series/product_knowledge/k10_mock_adapter.py`
  and `docs/k_series/K10C_*.md` were created.
- [ ] `unit_conversion.py` was not modified.
- [ ] `unit_payloads.py` was not modified.
- [ ] `service.py` was not modified.
- [ ] `schemas.py` was not modified.
- [ ] `router.py` was not modified.
- [ ] `models.py` was not modified.
- [ ] `__init__.py` was not modified.
- [ ] No router was registered.
- [ ] No frontend was written.
- [ ] No tests were written.
- [ ] No migration was created.
- [ ] Docker, Alembic, Postgres, staging, and production were not run.
- [ ] Env was not read.
- [ ] Live services were not connected.
- [ ] P-series workflow JSON was not read or modified.

# Mock Adapter Behavior

- [ ] Mock result marks `live_provider_called = false`.
- [ ] AI output allows only `draft` or `needs_review`.
- [ ] AI guessing is forbidden.
- [ ] Missing or unknown values do not become `0`.
- [ ] Provider secrets are not emitted.
- [ ] Provider request IDs are not emitted.
- [ ] Real model call IDs are not emitted.
- [ ] Free text parsing is not implemented in K10C.
- [ ] Unit payload draft helper returns missing value/unit errors when explicit
  values are absent.
- [ ] `reviewer_corrected` remains `false` for mock output.

# Follow-Up Gates

- [ ] K10D still requires separate owner approval.
- [ ] K10 live adapter remains blocked.
- [ ] Runtime integration remains blocked.
- [ ] Service integration remains blocked.
- [ ] Router registration remains blocked.
- [ ] DeepSeek live provider credentials remain blocked.
