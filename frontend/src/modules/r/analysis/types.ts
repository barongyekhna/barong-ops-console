export type RaProviderRoleStatus = {
  role: string;
  service: string;
  label: string;
  configured: boolean;
  source: string;
  model_env: string | null;
  model_name: string | null;
  base_url_env: string | null;
  base_url_configured: boolean;
};

export type RaSkillFile = {
  key: string;
  label: string;
  filename: string;
  exists: boolean;
  sha256: string | null;
  bytes: number;
};

export type RaStage = {
  id: string;
  label: string;
  owner: string;
  status: string;
  description: string;
};

export type RaChannel = {
  id: string;
  label: string;
  description: string;
  manual_trigger: boolean;
};

export type RaTableStatus = {
  name: string;
  label: string;
  exists: boolean;
  row_count: number | null;
};

export type RaFrameworkStatus = {
  module: string;
  label: string;
  organization_id: string;
  status: string;
  runtime_mode: string;
  execution_enabled: boolean;
  external_calls_enabled: boolean;
  manual_trigger_only: boolean;
  data_boundary: {
    reads: string[];
    writes: string[];
    cross_module_writes: boolean;
  };
  candidate_source: {
    status: string;
    total_products: number;
    ra_eligible: number;
    deepseek_passed: number;
    rule_passed: number;
    rejected: number;
    source_table: string;
  };
  tables: RaTableStatus[];
  skill: {
    loaded: boolean;
    name: string;
    version: string;
    description: string;
    docs_dir: string;
    files: RaSkillFile[];
    channels: Array<{
      channel: string;
      files: string[];
      loaded: boolean;
    }>;
    prompt_content_exposed: boolean;
  };
  providers: {
    roles: RaProviderRoleStatus[];
    routing: Record<string, string>;
    external_calls_enabled: boolean;
  };
  channels: RaChannel[];
  stages: RaStage[];
  next_steps: string[];
};

