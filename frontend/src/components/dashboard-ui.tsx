import Link from "next/link";

export type ModuleCardStatus = "active" | "disabled" | "error";

export type ActivityFeedItem = {
  badge: string;
  detail: string;
  meta: string;
  title: string;
  tone?: ModuleCardStatus;
};

type MetricCardProps = {
  detail: string;
  label: string;
  value: string | number;
};

type ModuleCardProps = {
  actionHref: string;
  actionLabel: string;
  badge: string;
  description: string;
  name: string;
  status: ModuleCardStatus;
};

type ActivityFeedProps = {
  items: ActivityFeedItem[];
};

const STATUS_LABELS: Record<ModuleCardStatus, string> = {
  active: "active",
  disabled: "disabled",
  error: "error",
};

export function MetricCard({ detail, label, value }: MetricCardProps) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

export function ModuleCard({
  actionHref,
  actionLabel,
  badge,
  description,
  name,
  status,
}: ModuleCardProps) {
  const disabled = status !== "active";

  return (
    <article className="module-card">
      <div className="module-card-header">
        <div>
          <span className={`status-pill ${status}`}>
            <span aria-hidden="true" />
            {STATUS_LABELS[status]}
          </span>
          <h3>{name}</h3>
        </div>
        <span className="subtle-badge">{badge}</span>
      </div>
      <p>{description}</p>
      {disabled ? (
        <button className="module-card-action" disabled type="button">
          {actionLabel}
        </button>
      ) : (
        <Link className="module-card-action" href={actionHref}>
          {actionLabel}
        </Link>
      )}
    </article>
  );
}

export function ActivityFeed({ items }: ActivityFeedProps) {
  return (
    <article className="activity-feed">
      <div className="activity-feed-heading">
        <h2>Activity feed</h2>
        <span>Live workspace updates</span>
      </div>
      <ol>
        {items.map((item, index) => (
          <li key={`${item.title}-${index}`}>
            <span className={`activity-dot ${item.tone ?? "active"}`} />
            <div>
              <div className="activity-row">
                <strong>{item.title}</strong>
                <span className="subtle-badge">{item.badge}</span>
              </div>
              <p>{item.detail}</p>
              <small>{item.meta}</small>
            </div>
          </li>
        ))}
      </ol>
    </article>
  );
}

export function DashboardSkeleton() {
  return (
    <div className="dashboard-skeleton" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}
