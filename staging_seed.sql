-- PRE20-P Batch-10 deterministic staging seed.
-- Scope: staging reset/bootstrap only. Do not run against production.

BEGIN;

INSERT INTO users (
    username,
    password_hash,
    role,
    is_active,
    failed_login_count
) VALUES
    (
        'staging_owner_seed',
        '$argon2id$v=19$m=19456,t=2,p=1$wLSLtVx//KLy6MZwTkDNbg$AnW3ZCv1maBwYu9CCGwPQLgqF4rj/KgfVnDCKjZQEvo',
        'owner',
        true,
        0
    ),
    (
        'staging_viewer_seed',
        '$argon2id$v=19$m=19456,t=2,p=1$z6+IzShBsVXNNlGNrOtV5Q$jvTTj80Qni+wEyXkxdflIooY7jqsJ9OdrujCrKHExwU',
        'viewer',
        true,
        0
    )
ON CONFLICT (username) DO UPDATE SET
    role = EXCLUDED.role,
    is_active = EXCLUDED.is_active,
    failed_login_count = 0,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO permission_registry (
    id,
    permission_key,
    module_key,
    category,
    action,
    label,
    description,
    risk_level,
    menu_policy,
    is_system,
    is_enabled
) VALUES
    (
        '00000000-0000-0000-0000-000000000501',
        'staging.health.read',
        'system.health',
        'system',
        'read',
        'Read staging health',
        'Deterministic staging health permission.',
        'low',
        'show_locked',
        true,
        true
    ),
    (
        '00000000-0000-0000-0000-000000000502',
        'staging.observability.read',
        'system.observability',
        'system',
        'read',
        'Read staging observability',
        'Deterministic staging C17 observability permission.',
        'medium',
        'show_locked',
        true,
        true
    ),
    (
        '00000000-0000-0000-0000-000000000503',
        'staging.modules.read',
        'system.modules',
        'system',
        'read',
        'Read staging modules',
        'Deterministic staging module metadata permission.',
        'low',
        'show_locked',
        true,
        true
    )
ON CONFLICT (permission_key) DO UPDATE SET
    module_key = EXCLUDED.module_key,
    category = EXCLUDED.category,
    action = EXCLUDED.action,
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    risk_level = EXCLUDED.risk_level,
    menu_policy = EXCLUDED.menu_policy,
    is_system = true,
    is_enabled = true,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO role_default_permissions (
    id,
    role,
    permission_key,
    scope_type,
    scope_key,
    is_enabled
) VALUES
    (
        '00000000-0000-0000-0000-000000000511',
        'owner',
        'staging.health.read',
        'global',
        '*',
        true
    ),
    (
        '00000000-0000-0000-0000-000000000512',
        'owner',
        'staging.observability.read',
        'global',
        '*',
        true
    ),
    (
        '00000000-0000-0000-0000-000000000513',
        'viewer',
        'staging.health.read',
        'global',
        '*',
        true
    ),
    (
        '00000000-0000-0000-0000-000000000514',
        'viewer',
        'staging.modules.read',
        'global',
        '*',
        true
    )
ON CONFLICT (role, permission_key, scope_type, scope_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    updated_at = CURRENT_TIMESTAMP;

WITH owner_user AS (
    SELECT id::text AS user_id
    FROM users
    WHERE username = 'staging_owner_seed'
)
INSERT INTO organizations (
    org_id,
    name,
    org_name,
    org_type,
    owner_user_id,
    status,
    metadata
) SELECT
    'org_11111111111111111111111111111111',
    'Staging Primary Org',
    'Staging Primary Org',
    'store',
    owner_user.user_id,
    'active',
    '{"seed":"PRE20-P Batch-10","deterministic":true}'::jsonb
FROM owner_user
ON CONFLICT (org_id) DO UPDATE SET
    name = EXCLUDED.name,
    org_name = EXCLUDED.org_name,
    org_type = EXCLUDED.org_type,
    owner_user_id = EXCLUDED.owner_user_id,
    status = EXCLUDED.status,
    metadata = EXCLUDED.metadata,
    updated_at = CURRENT_TIMESTAMP;

WITH users_by_name AS (
    SELECT username, id::text AS user_id
    FROM users
    WHERE username IN ('staging_owner_seed', 'staging_viewer_seed')
)
INSERT INTO org_memberships (
    membership_id,
    user_id,
    org_id,
    role,
    status
) VALUES
    (
        'mem_staging_owner_primary',
        (SELECT user_id FROM users_by_name WHERE username = 'staging_owner_seed'),
        'org_11111111111111111111111111111111',
        'owner',
        'active'
    ),
    (
        'mem_staging_viewer_primary',
        (SELECT user_id FROM users_by_name WHERE username = 'staging_viewer_seed'),
        'org_11111111111111111111111111111111',
        'member',
        'active'
    )
ON CONFLICT (user_id, org_id) DO UPDATE SET
    role = EXCLUDED.role,
    status = EXCLUDED.status;

INSERT INTO module_registry (
    module_id,
    name,
    responsibilities,
    non_responsibilities,
    input_schema,
    output_schema,
    permissions,
    risk_level,
    version,
    status,
    dependencies,
    artifact_types,
    review_types,
    error_codes,
    healthcheck_config,
    rollback_policy
) VALUES
    (
        'staging.health',
        'Staging Health Module',
        '["staging health contract validation"]'::jsonb,
        '["production traffic","business execution"]'::jsonb,
        '{"type":"object","additionalProperties":false}'::jsonb,
        '{"type":"object","required":["status"]}'::jsonb,
        '["staging.health.read"]'::jsonb,
        'low',
        '1.0.0',
        'active',
        '[]'::jsonb,
        '[]'::jsonb,
        '[]'::jsonb,
        '[]'::jsonb,
        '{"path":"/api/public/health"}'::jsonb,
        '{"rollback_safe":true,"strategy":"stateless"}'::jsonb
    ),
    (
        'staging.observability',
        'Staging Observability Module',
        '["event_streams validation","ops_alerts validation"]'::jsonb,
        '["production alert delivery"]'::jsonb,
        '{"type":"object","additionalProperties":true}'::jsonb,
        '{"type":"object","required":["pipeline"]}'::jsonb,
        '["staging.observability.read"]'::jsonb,
        'medium',
        '1.0.0',
        'active',
        '["staging.health"]'::jsonb,
        '[]'::jsonb,
        '[]'::jsonb,
        '[]'::jsonb,
        '{"tables":["event_streams","anomaly_events","ops_alerts"]}'::jsonb,
        '{"rollback_safe":true,"strategy":"validate_manifest_before_after"}'::jsonb
    )
ON CONFLICT (module_id) DO UPDATE SET
    name = EXCLUDED.name,
    responsibilities = EXCLUDED.responsibilities,
    non_responsibilities = EXCLUDED.non_responsibilities,
    input_schema = EXCLUDED.input_schema,
    output_schema = EXCLUDED.output_schema,
    permissions = EXCLUDED.permissions,
    risk_level = EXCLUDED.risk_level,
    version = EXCLUDED.version,
    status = EXCLUDED.status,
    dependencies = EXCLUDED.dependencies,
    artifact_types = EXCLUDED.artifact_types,
    review_types = EXCLUDED.review_types,
    error_codes = EXCLUDED.error_codes,
    healthcheck_config = EXCLUDED.healthcheck_config,
    rollback_policy = EXCLUDED.rollback_policy,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO module_bindings (
    org_id,
    module_id,
    status
) VALUES
    ('org_11111111111111111111111111111111', 'staging.health', 'enabled'),
    ('org_11111111111111111111111111111111', 'staging.observability', 'enabled')
ON CONFLICT (org_id, module_id) DO UPDATE SET
    status = EXCLUDED.status,
    updated_at = CURRENT_TIMESTAMP;

COMMIT;
