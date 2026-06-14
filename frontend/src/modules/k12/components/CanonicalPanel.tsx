import type {
  ProductAiCanonicalFields,
  RawProductInput,
  ReviewItem,
} from "../services/k12Api";
import { reviewItemStatusLabels } from "../services/reviewState";

type CanonicalPanelProps = {
  canonical: ProductAiCanonicalFields;
  isEditingCanonical: boolean;
  onCanonicalChange: (value: string) => void;
  rawInput: RawProductInput;
  reviewItem: ReviewItem;
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

export function CanonicalPanel({
  canonical,
  isEditingCanonical,
  onCanonicalChange,
  rawInput,
  reviewItem,
}: CanonicalPanelProps) {
  return (
    <section
      className="k12-review-panel k12-canonical-panel"
      aria-labelledby="k12-canonical"
    >
      <header className="k12-review-panel-heading">
        <div>
          <span className="eyebrow">Canonical Approval</span>
          <h3 id="k12-canonical">Review Item</h3>
        </div>
        <strong className="k12-review-status-badge">
          {reviewItemStatusLabels[reviewItem.status]}
        </strong>
      </header>

      <div className="k12-review-field k12-review-key-field">
        <span>raw input from K06</span>
        <p>{reviewItem.raw}</p>
      </div>

      <div className="k12-review-field">
        <span>raw language</span>
        <strong>{rawInput.original_language}</strong>
      </div>

      <div className="k12-review-field k12-review-key-field">
        <span>canonical placeholder</span>
        {isEditingCanonical ? (
          <textarea
            aria-label="Edit canonical placeholder"
            className="k12-canonical-textarea"
            onChange={(event) => onCanonicalChange(event.target.value)}
            value={reviewItem.canonical}
          />
        ) : (
          <p>{reviewItem.canonical}</p>
        )}
      </div>

      <div className="k12-review-field k12-review-ai-placeholder">
        <span>ai_suggestion placeholder</span>
        <p>{reviewItem.ai_suggestion}</p>
      </div>

      <header className="k12-review-subheading">
        <span className="eyebrow">Structured Canonical</span>
        <h4>Mock AI Fields</h4>
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
