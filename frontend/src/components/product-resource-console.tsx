"use client";

import {
  CheckCircle2,
  LoaderCircle,
  RotateCcw,
  Save,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { ApiError, apiRequest } from "@/lib/api";

type ProductRecord = Record<string, unknown>;

export type ProductRecordField = {
  key: string;
  label: string;
};

export type ProductFormField = {
  key: string;
  label: string;
  type?: "text" | "number" | "select" | "textarea" | "json" | "csv" | "hidden";
  defaultValue?: string;
  includeIfEmpty?: boolean;
  options?: Array<{ label: string; value: string }>;
  placeholder?: string;
  required?: boolean;
};

export type ProductResourceCreateConfig = {
  description: string;
  endpoint: string;
  fields: ProductFormField[];
  submitLabel: string;
  title: string;
  buildPayload?: (values: ProductRecord) => ProductRecord;
};

export type ProductResourceAction = {
  description: string;
  endpoint: string | ((record: ProductRecord) => string);
  fields: ProductFormField[];
  key: string;
  label: string;
  method?: "POST" | "PATCH" | "DELETE";
  submitLabel: string;
  title: string;
  variant?: "primary" | "secondary" | "danger";
  buildPayload?: (values: ProductRecord, record: ProductRecord) => ProductRecord;
  disabled?: (record: ProductRecord) => boolean;
};

export type ProductRelatedList = {
  endpoint: (record: ProductRecord) => string;
  fields: ProductRecordField[];
  key: string;
  title: string;
};

type ProductResourceConsoleProps = {
  actions?: ProductResourceAction[];
  create?: ProductResourceCreateConfig;
  description: string;
  detailEndpoint?: (record: ProductRecord) => string;
  detailFields: ProductRecordField[];
  emptyDescription: string;
  emptyTitle: string;
  endpoint: string;
  eyebrow: string;
  fields: ProductRecordField[];
  idKey: string;
  relatedLists?: ProductRelatedList[];
  requiredPermission: string;
  title: string;
};

type ListPayload = {
  count: number;
  items: ProductRecord[];
  limit: number;
  offset: number;
};

function isRecord(value: unknown): value is ProductRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message || fallback;
  }
  return fallback;
}

function normalizeListPayload(value: unknown): ListPayload {
  if (Array.isArray(value)) {
    const items = value.filter(isRecord);
    return {
      count: items.length,
      items,
      limit: items.length,
      offset: 0,
    };
  }

  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items.filter(isRecord)
    : [];

  return {
    count:
      typeof record.count === "number" && Number.isFinite(record.count)
        ? record.count
        : items.length,
    items,
    limit:
      typeof record.limit === "number" && Number.isFinite(record.limit)
        ? record.limit
        : items.length,
    offset:
      typeof record.offset === "number" && Number.isFinite(record.offset)
        ? record.offset
        : 0,
  };
}

function readField(record: ProductRecord | null | undefined, key: string) {
  if (!record) {
    return undefined;
  }

  return key.split(".").reduce<unknown>((current, part) => {
    if (!isRecord(current)) {
      return undefined;
    }
    return current[part];
  }, record);
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "Not set";
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join(", ") : "None";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function recordId(record: ProductRecord, idKey: string, index = 0) {
  return String(readField(record, idKey) ?? record.id ?? `record-${index}`);
}

function fieldDefaults(fields: ProductFormField[]) {
  return Object.fromEntries(
    fields.map((field) => [field.key, field.defaultValue ?? ""]),
  ) as Record<string, string>;
}

function parseFieldValue(field: ProductFormField, value: string) {
  if (field.type === "number") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }

  if (field.type === "json") {
    const trimmed = value.trim();
    if (!trimmed) {
      return field.required ? {} : undefined;
    }
    return JSON.parse(trimmed);
  }

  if (field.type === "csv") {
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean);
  }

  return value;
}

function buildPayload(fields: ProductFormField[], values: Record<string, string>) {
  const payload: ProductRecord = {};

  for (const field of fields) {
    const value = values[field.key] ?? "";
    const trimmed = value.trim();
    const shouldInclude =
      field.required ||
      field.includeIfEmpty ||
      field.type === "hidden" ||
      trimmed.length > 0;

    if (!shouldInclude) {
      continue;
    }

    const parsed = parseFieldValue(field, value);
    if (parsed !== undefined || field.includeIfEmpty) {
      payload[field.key] = parsed;
    }
  }

  return payload;
}

function ResourceForm({
  disabled,
  fields,
  onSubmit,
  submitLabel,
  submitVariant = "primary",
}: {
  disabled?: boolean;
  fields: ProductFormField[];
  onSubmit: (payload: ProductRecord) => Promise<void>;
  submitLabel: string;
  submitVariant?: "primary" | "secondary" | "danger";
}) {
  const [values, setValues] = useState(() => fieldDefaults(fields));
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const visibleFields = fields.filter((field) => field.type !== "hidden");
  const buttonClass =
    submitVariant === "danger"
      ? "danger-button"
      : submitVariant === "secondary"
        ? "secondary-button"
        : "primary-button";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      await onSubmit(buildPayload(fields, values));
      setValues(fieldDefaults(fields));
    } catch (formError) {
      setError(errorMessage(formError, "The action could not be completed."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="product-form" onSubmit={(event) => void handleSubmit(event)}>
      {visibleFields.map((field) => (
        <label className="field-group" key={field.key}>
          <span>{field.label}</span>
          {field.type === "select" ? (
            <select
              className="select-shell"
              disabled={disabled || isSubmitting}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  [field.key]: event.target.value,
                }))
              }
              required={field.required}
              value={values[field.key] ?? ""}
            >
              {(field.options ?? []).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : field.type === "textarea" || field.type === "json" ? (
            <span className="textarea-shell">
              <textarea
                disabled={disabled || isSubmitting}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
                placeholder={field.placeholder}
                required={field.required}
                value={values[field.key] ?? ""}
              />
            </span>
          ) : (
            <span className="input-shell">
              <input
                disabled={disabled || isSubmitting}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
                placeholder={field.placeholder}
                required={field.required}
                type={field.type === "number" ? "number" : "text"}
                value={values[field.key] ?? ""}
              />
            </span>
          )}
        </label>
      ))}
      <div aria-live="polite" className="form-message">
        {error}
      </div>
      <button className={buttonClass} disabled={disabled || isSubmitting} type="submit">
        {isSubmitting ? (
          <LoaderCircle aria-hidden="true" className="spin" size={17} />
        ) : submitVariant === "primary" ? (
          <Save aria-hidden="true" size={17} />
        ) : (
          <CheckCircle2 aria-hidden="true" size={17} />
        )}
        {isSubmitting ? "Working" : submitLabel}
      </button>
    </form>
  );
}

function RelatedRecords({
  list,
  record,
}: {
  list: ProductRelatedList;
  record: ProductRecord;
}) {
  const [payload, setPayload] = useState<ListPayload | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const endpoint = useMemo(() => list.endpoint(record), [list, record]);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setPayload(normalizeListPayload(await apiRequest<unknown>(endpoint)));
    } catch (requestError) {
      setPayload(null);
      setError(errorMessage(requestError, "Related records are unavailable."));
    } finally {
      setIsLoading(false);
    }
  }, [endpoint]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <article className="ops-panel product-related-panel">
      <div className="ops-panel-heading">
        <div>
          <h3>{list.title}</h3>
          <p>{endpoint}</p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={15} />
          ) : (
            <RotateCcw aria-hidden="true" size={15} />
          )}
          Refresh
        </button>
      </div>

      {isLoading ? (
        <div className="ops-empty-state" role="status">
          <strong>Loading related records</strong>
          <span>{endpoint}</span>
        </div>
      ) : error ? (
        <div className="ops-empty-state" role="alert">
          <strong>Related records unavailable</strong>
          <span>{error}</span>
        </div>
      ) : payload?.items.length ? (
        <ol className="ops-record-list">
          {payload.items.map((item, index) => (
            <li key={recordId(item, list.fields[0]?.key ?? "id", index)}>
              <span>{displayValue(readField(item, list.fields[0]?.key ?? "id"))}</span>
              {list.fields.slice(1).map((field) => (
                <small key={field.key}>
                  {field.label}: {displayValue(readField(item, field.key))}
                </small>
              ))}
            </li>
          ))}
        </ol>
      ) : (
        <div className="ops-empty-state">
          <strong>No related records</strong>
          <span>{endpoint}</span>
        </div>
      )}
    </article>
  );
}

export function ProductResourceConsole({
  actions = [],
  create,
  description,
  detailEndpoint,
  detailFields,
  emptyDescription,
  emptyTitle,
  endpoint,
  eyebrow,
  fields,
  idKey,
  relatedLists = [],
  requiredPermission,
  title,
}: ProductResourceConsoleProps) {
  const [payload, setPayload] = useState<ListPayload | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProductRecord | null>(null);
  const [detailError, setDetailError] = useState("");
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [notice, setNotice] = useState("");

  const items = payload?.items ?? [];
  const selectedRecord = useMemo(
    () =>
      items.find((item, index) => recordId(item, idKey, index) === selectedId) ??
      null,
    [idKey, items, selectedId],
  );
  const activeDetail = detail ?? selectedRecord;

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const result = normalizeListPayload(await apiRequest<unknown>(endpoint));
      setPayload(result);
      setSelectedId((current) => {
        if (
          current &&
          result.items.some((item, index) => recordId(item, idKey, index) === current)
        ) {
          return current;
        }
        return result.items[0] ? recordId(result.items[0], idKey, 0) : null;
      });
    } catch (requestError) {
      setPayload(null);
      setSelectedId(null);
      setError(errorMessage(requestError, `${title} are unavailable.`));
    } finally {
      setIsLoading(false);
    }
  }, [endpoint, idKey, title]);

  const loadDetail = useCallback(
    async (record: ProductRecord | null) => {
      if (!record || !detailEndpoint) {
        setDetail(record);
        setDetailError("");
        setIsDetailLoading(false);
        return;
      }

      setIsDetailLoading(true);
      setDetailError("");
      try {
        setDetail(await apiRequest<ProductRecord>(detailEndpoint(record)));
      } catch (requestError) {
        setDetail(record);
        setDetailError(errorMessage(requestError, "Detail is unavailable."));
      } finally {
        setIsDetailLoading(false);
      }
    },
    [detailEndpoint],
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadDetail(selectedRecord);
  }, [loadDetail, selectedRecord]);

  async function submitCreate(values: ProductRecord) {
    if (!create) {
      return;
    }
    const body = create.buildPayload ? create.buildPayload(values) : values;
    const created = await apiRequest<ProductRecord>(create.endpoint, {
      body,
      method: "POST",
    });
    setNotice(`${create.title} saved.`);
    await load();
    setSelectedId(recordId(created, idKey));
  }

  async function submitAction(action: ProductResourceAction, values: ProductRecord) {
    if (!selectedRecord) {
      return;
    }
    const target =
      typeof action.endpoint === "function"
        ? action.endpoint(selectedRecord)
        : action.endpoint;
    const body = action.buildPayload
      ? action.buildPayload(values, selectedRecord)
      : values;

    const updated = await apiRequest<ProductRecord>(target, {
      body,
      method: action.method ?? "POST",
    });
    setNotice(`${action.label} completed.`);
    setDetail(updated);
    await load();
  }

  const selectedLabel = selectedRecord
    ? recordId(selectedRecord, idKey)
    : "No selection";

  return (
    <section className="product-console" aria-label={title}>
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Records</span>
          <strong>{payload?.count ?? 0}</strong>
        </div>
        <div>
          <span>Selected</span>
          <strong>{selectedLabel}</strong>
        </div>
        <div>
          <span>API</span>
          <strong>{endpoint}</strong>
        </div>
        <div>
          <span>Permission</span>
          <strong>{requiredPermission}</strong>
        </div>
      </div>

      {notice ? (
        <p className="ops-warning product-notice" role="status">
          {notice}
        </p>
      ) : null}

      {isLoading ? (
        <section className="list-state" aria-label={`Loading ${title}`}>
          <LoaderCircle className="spin" aria-hidden="true" size={22} />
          <span>Loading records</span>
        </section>
      ) : error ? (
        <section className="list-state list-error" role="alert">
          <div>
            <h2>{title} are unavailable</h2>
            <p>{error}</p>
          </div>
          <button className="primary-button" onClick={() => void load()} type="button">
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        </section>
      ) : (
        <div className="product-console-grid">
          <article className="ops-panel product-list-panel">
            <div className="ops-panel-heading">
              <div>
                <h3>List</h3>
                <p>{endpoint}</p>
              </div>
              <span className="ops-source">{items.length} shown</span>
            </div>

            {items.length === 0 ? (
              <div className="ops-empty-state">
                <strong>{emptyTitle}</strong>
                <span>{emptyDescription}</span>
              </div>
            ) : (
              <div className="module-registry-table-scroll product-table-scroll">
                <table className="module-registry-table product-table">
                  <thead>
                    <tr>
                      {fields.map((field) => (
                        <th key={field.key}>{field.label}</th>
                      ))}
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, index) => {
                      const id = recordId(item, idKey, index);
                      const active = id === selectedId;

                      return (
                        <tr className={active ? "selected-row" : ""} key={id}>
                          {fields.map((field) => (
                            <td key={field.key}>
                              <strong>{displayValue(readField(item, field.key))}</strong>
                            </td>
                          ))}
                          <td>
                            <button
                              className="secondary-button"
                              onClick={() => setSelectedId(id)}
                              type="button"
                            >
                              View
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          <article className="ops-panel product-detail-panel">
            <div className="ops-panel-heading">
              <div>
                <h3>Detail</h3>
                <p>{selectedLabel}</p>
              </div>
              {isDetailLoading ? (
                <LoaderCircle aria-hidden="true" className="spin" size={17} />
              ) : null}
            </div>

            {detailError ? (
              <p className="ops-warning">{detailError}</p>
            ) : null}

            {activeDetail ? (
              <dl className="ops-readiness-list product-detail-list">
                {detailFields.map((field) => (
                  <div key={field.key}>
                    <dt>{field.label}</dt>
                    <dd>{displayValue(readField(activeDetail, field.key))}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <div className="ops-empty-state">
                <strong>No record selected</strong>
                <span>Select a list row to inspect the detail payload.</span>
              </div>
            )}

            {activeDetail && actions.length > 0 ? (
              <div className="product-action-stack">
                {actions.map((action) => {
                  const disabled = action.disabled?.(activeDetail) ?? false;
                  return (
                    <article className="product-action" key={action.key}>
                      <div>
                        <h4>{action.title}</h4>
                        <p>{action.description}</p>
                      </div>
                      <ResourceForm
                        disabled={disabled}
                        fields={action.fields}
                        onSubmit={(values) => submitAction(action, values)}
                        submitLabel={action.submitLabel}
                        submitVariant={action.variant}
                      />
                    </article>
                  );
                })}
              </div>
            ) : null}
          </article>
        </div>
      )}

      {selectedRecord
        ? relatedLists.map((list) => (
            <RelatedRecords
              key={`${list.key}-${recordId(selectedRecord, idKey)}`}
              list={list}
              record={selectedRecord}
            />
          ))
        : null}

      {create ? (
        <article className="ops-panel product-create-panel">
          <div className="ops-panel-heading">
            <div>
              <h3>{create.title}</h3>
              <p>{create.description}</p>
            </div>
            <span className="ops-source">{create.endpoint}</span>
          </div>
          <ResourceForm
            fields={create.fields}
            onSubmit={submitCreate}
            submitLabel={create.submitLabel}
          />
        </article>
      ) : null}
    </section>
  );
}

export function idWithPrefix(prefix: string) {
  return `${prefix}_${Date.now()}`;
}

export function fixedPayload(payload: ProductRecord) {
  return () => payload;
}
