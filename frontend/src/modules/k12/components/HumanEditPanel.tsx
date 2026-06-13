import type { ProductHumanEditFields } from "../services/k12Api";

type HumanEditPanelProps = {
  value: ProductHumanEditFields;
  onChange: (value: ProductHumanEditFields) => void;
};

type ListField = "features" | "warnings";
type MapField = "specs" | "dimensions";

function listToText(values: string[]) {
  return values.join("\n");
}

function textToList(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function HumanEditPanel({ value, onChange }: HumanEditPanelProps) {
  function updateField<K extends keyof ProductHumanEditFields>(
    field: K,
    nextValue: ProductHumanEditFields[K],
  ) {
    onChange({
      ...value,
      [field]: nextValue,
    });
  }

  function updateListField(field: ListField, nextValue: string) {
    updateField(field, textToList(nextValue));
  }

  function updateMapField(field: MapField, key: string, nextValue: string) {
    updateField(field, {
      ...value[field],
      [key]: nextValue,
    });
  }

  return (
    <form
      className="k12-review-form"
      onSubmit={(event) => event.preventDefault()}
    >
      <div className="field-group">
        <label htmlFor="k12-human-title">title</label>
        <div className="input-shell">
          <input
            id="k12-human-title"
            onChange={(event) => updateField("title", event.target.value)}
            value={value.title}
          />
        </div>
      </div>

      <div className="field-group">
        <label htmlFor="k12-human-description">description</label>
        <div className="textarea-shell">
          <textarea
            id="k12-human-description"
            onChange={(event) =>
              updateField("description", event.target.value)
            }
            value={value.description}
          />
        </div>
      </div>

      <div className="field-group">
        <label htmlFor="k12-human-features">features</label>
        <div className="textarea-shell">
          <textarea
            id="k12-human-features"
            onChange={(event) =>
              updateListField("features", event.target.value)
            }
            value={listToText(value.features)}
          />
        </div>
      </div>

      <fieldset className="k12-review-fieldset">
        <legend>specs</legend>
        {Object.entries(value.specs).map(([key, specValue]) => (
          <label className="k12-review-map-input" key={key}>
            <span>{key}</span>
            <input
              onChange={(event) =>
                updateMapField("specs", key, event.target.value)
              }
              value={specValue}
            />
          </label>
        ))}
      </fieldset>

      <fieldset className="k12-review-fieldset">
        <legend>dimensions</legend>
        {Object.entries(value.dimensions).map(([key, dimensionValue]) => (
          <label className="k12-review-map-input" key={key}>
            <span>{key}</span>
            <input
              onChange={(event) =>
                updateMapField("dimensions", key, event.target.value)
              }
              value={dimensionValue}
            />
          </label>
        ))}
      </fieldset>

      <div className="field-group">
        <label htmlFor="k12-human-weight">weight</label>
        <div className="input-shell">
          <input
            id="k12-human-weight"
            onChange={(event) => updateField("weight", event.target.value)}
            value={value.weight}
          />
        </div>
      </div>

      <div className="field-group">
        <label htmlFor="k12-human-warnings">warnings</label>
        <div className="textarea-shell">
          <textarea
            id="k12-human-warnings"
            onChange={(event) =>
              updateListField("warnings", event.target.value)
            }
            value={listToText(value.warnings)}
          />
        </div>
      </div>
    </form>
  );
}
