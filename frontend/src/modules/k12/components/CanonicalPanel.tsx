import type { ProductAiCanonicalFields } from "../services/k12Api";

type CanonicalPanelProps = {
  canonical: ProductAiCanonicalFields;
};

function ListValue({ values }: { values: string[] }) {
  return (
    <ul className="k12-review-value-list">
      {values.map((value) => (
        <li key={value}>{value}</li>
      ))}
    </ul>
  );
}

function MapValue({ values }: { values: Record<string, string> }) {
  return (
    <dl className="k12-review-map">
      {Object.entries(values).map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CanonicalPanel({ canonical }: CanonicalPanelProps) {
  return (
    <section className="k12-review-panel" aria-labelledby="k12-canonical">
      <header className="k12-review-panel-heading">
        <span className="eyebrow">AI Canonical</span>
        <h3 id="k12-canonical">Mock Canonical</h3>
      </header>

      <div className="k12-review-field k12-review-key-field">
        <span>title (EN)</span>
        <strong>{canonical.title}</strong>
      </div>

      <div className="k12-review-field k12-review-key-field">
        <span>description (EN)</span>
        <p>{canonical.description}</p>
      </div>

      <div className="k12-review-field">
        <span>features</span>
        <ListValue values={canonical.features} />
      </div>

      <div className="k12-review-field">
        <span>specs</span>
        <MapValue values={canonical.specs} />
      </div>

      <div className="k12-review-field">
        <span>dimensions</span>
        <MapValue values={canonical.dimensions} />
      </div>

      <div className="k12-review-field k12-review-key-field">
        <span>weight</span>
        <strong>{canonical.weight}</strong>
      </div>
    </section>
  );
}
