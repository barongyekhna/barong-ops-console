# K09F K08B Recommendation

Status: K09F recommendation, pending owner review.

Date: 2026-06-12.

# 1. Recommendation summary

- 是否立即进入 K08B：recommended, but docs-only and not a runtime blocker.
- 是否可以先继续 K09G/K09H：yes, if owner prefers to continue K09 docs flow first. K09F found clarification gaps, not code blockers.
- 是否可以先做 K07A hidden UI info architecture：yes. K07A can proceed if it stays hidden-by-default, docs/design only, and avoids runtime/menu/API exposure.
- 是否不建议进入 K09I runtime integration：yes. K09I remains blocked because K06 runtime registration and owner-approved runtime strategy are still deferred.

K09F recommends K08B before runtime integration and before K09-SEAL, because K08B can cheaply align K08 field docs with the K09B/K09E nested payload contract.

# 2. Recommended K08B if needed

Recommended K08B scope: docs only.

K08B may update:

- `K08_CANONICAL_FIELD_DICTIONARY.md`
- `K08_REQUIRED_OPTIONAL_FIELD_MATRIX.md`
- `K08_READINESS_GATES.md`
- `K08_AI_HUMAN_REVIEW_POLICY.md`
- `K08_DOWNSTREAM_CONSUMPTION_MAPPING.md`

K08B should stay limited to:

- Linking `dimensions_json`, `package_dimensions_json`, `weight_json`, and `package_weight_json` to the K09 Unit Value Payload contract.
- Clarifying nested payload fields are JSON contract fields, not product-table columns.
- Clarifying product/package separation and net/gross/package/shipping distinction.
- Clarifying that unit payload blocking errors block dependent downstream gates.
- Clarifying that AI may structure explicit unit values but cannot infer missing dimensions, weight values, net/gross distinction, or product/package context.
- Clarifying K09C/E no free-text parser boundary.
- Mentioning K09 `unit_payloads.py` as future helper reference only, not runtime integration.

K08B cannot:

- 写 code
- 改 migration
- 改 backend runtime
- 改 frontend
- 改 tests
- 接 API
- 接 live services
- 读 P-series workflow JSON

# 3. K09 continuation recommendation

- 如果 K09F 发现 K08 只需轻微澄清，可继续 K09G/K09H 或先做 K07A。
- 如果 K09F 发现 K08 gate policy 有中高风险 gap，应先做 K08B。
- K09I runtime integration 仍 blocked，需要 K06 runtime strategy / owner approval。
- K09-SEAL 不能现在做，必须等 K09F/G/H 或 owner 决策。

K09F finding: K08 has medium documentation gaps around unit payload gate behavior, net/gross/package distinction, and no free-text parser boundary. These are not immediate helper blockers, but they are important before runtime integration or sealing.

# 4. Proposed next task

Options:

- Option A: K08B docs-only clarification.
- Option B: K09G K07 unit input guide.
- Option C: K09H K10 AI unit output rules.
- Option D: K07A hidden UI information architecture.

Recommended priority: Option A, K08B docs-only clarification.

Reason:

- K08B is small and documentation-only.
- K08B reduces ambiguity before K09G UI guidance and K09H AI output rules reuse the unit payload contract.
- K08B does not require runtime registration, DB, migration, frontend, tests, Docker, Alembic, Postgres, staging, production, env reads, live services, P-series workflow JSON, or n8n changes.
- K09I should not start until K06 runtime registration strategy and owner approval are available.
