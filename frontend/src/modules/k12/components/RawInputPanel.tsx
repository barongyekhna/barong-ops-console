import type { RawProductInput } from "../services/k12Api";

type RawInputPanelProps = {
  rawInput: RawProductInput;
};

function JsonViewer({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown>;
}) {
  return (
    <div className="k12-review-field">
      <span>{label}</span>
      <pre aria-readonly="true" className="k12-review-json">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export function RawInputPanel({ rawInput }: RawInputPanelProps) {
  return (
    <section className="k12-review-panel" aria-labelledby="k12-raw-input">
      <header className="k12-review-panel-heading">
        <span className="eyebrow">Raw Input</span>
        <h3 id="k12-raw-input">Source Payload</h3>
      </header>

      <div className="k12-review-field">
        <span>original_input_text</span>
        <p className="k12-review-readonly-text">
          {rawInput.original_input_text}
        </p>
      </div>

      <div className="k12-review-field">
        <span>original_language</span>
        <p className="k12-review-readonly-text">
          {rawInput.original_language}
        </p>
      </div>

      <JsonViewer label="original_json" value={rawInput.original_json} />

      {rawInput.serp_data ? (
        <JsonViewer label="serp_data" value={rawInput.serp_data} />
      ) : null}
    </section>
  );
}
