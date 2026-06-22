# Module Execution Human Explanation

Generated at: 2026-06-22

The real registry currently contains 15 modules. K-series, P-series, GMC, and SEO modules are not present as real manifests in this repository, so they are marked `not_registered` instead of being mocked.

Only one registered module declares an external dependency: `integration.n8n_test_bridge` declares `n8n`, but C14E marks that binding disabled and no API key capability is enabled by default. All other registered modules are local metadata, local admin, local approval, or local observability flows.

For future modules such as a K-series workflow, the intended execution chain is:

1. Generate the module prompt or execution payload.
2. Select the declared `key_alias`, for example `serper`, `openai`, or `deepseek`.
3. Resolve `org_id + module_id + key_alias` in the backend API key orchestration service.
4. Reject the call if the key is missing, disabled, deleted, unbound, or belongs to another org.
5. Inject the key only inside backend server memory.
6. Return the module result without returning key material to the frontend.

This expansion adds the backend injection resolver, but it does not invent missing K/P/GMC/SEO modules or fake provider calls.
