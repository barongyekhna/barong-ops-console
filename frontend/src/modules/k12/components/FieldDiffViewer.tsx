import {
  diffStatusLabels,
  getDiffSummaryStatus,
  isOverrideDiffStatus,
  type DiffStatus,
} from "../services/reviewState";

export type DiffPrimitive = string | number | boolean;
export type DiffInputValue =
  | DiffPrimitive
  | readonly DiffInputValue[]
  | { [key: string]: DiffInputValue }
  | null
  | undefined;
export type DiffOutputValue =
  | DiffPrimitive
  | DiffOutputValue[]
  | { [key: string]: DiffOutputValue }
  | null;

export type FieldDiffItem = {
  field: string;
  old_value: DiffOutputValue;
  new_value: DiffOutputValue;
  status: DiffStatus;
  path: string;
  is_override: boolean;
};

type FieldDiffViewerProps = {
  aiValue: DiffInputValue;
  humanValue: DiffInputValue;
  label: string;
  field?: string;
  leftLabel?: string;
  overlayLabel?: string;
  overlayValue?: DiffInputValue;
  rightLabel?: string;
};

type ArrayEntry = {
  index: number;
  key: string;
  value: DiffInputValue;
};

type ArrayPair = {
  oldIndex: number;
  newIndex: number;
  oldValue: DiffInputValue;
  newValue: DiffInputValue;
};

function normalizeFieldPath(value: string) {
  const path = value
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();

  return path || "field";
}

function getChildPath(parentPath: string, key: string) {
  return `${parentPath}.${key}`;
}

function getArrayPath(parentPath: string, index: number) {
  return `${parentPath}[${index}]`;
}

function isDiffObject(
  value: DiffInputValue,
): value is { [key: string]: DiffInputValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEffectivelyMissing(value: DiffInputValue) {
  if (value === null || value === undefined) {
    return true;
  }

  return typeof value === "string" && value.trim().length === 0;
}

function normalizeForCompare(value: DiffInputValue): DiffOutputValue {
  if (isEffectivelyMissing(value)) {
    return null;
  }

  if (typeof value === "string") {
    return value.trim();
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => normalizeForCompare(item));
  }

  if (isDiffObject(value)) {
    const normalized: { [key: string]: DiffOutputValue } = {};

    Object.keys(value)
      .sort((leftKey, rightKey) => leftKey.localeCompare(rightKey))
      .forEach((key) => {
        normalized[key] = normalizeForCompare(value[key]);
      });

    return normalized;
  }

  return null;
}

function toOutputValue(value: DiffInputValue): DiffOutputValue {
  return normalizeForCompare(value);
}

function stableSerialize(value: DiffInputValue) {
  return JSON.stringify(normalizeForCompare(value));
}

function buildDiffItem(
  path: string,
  oldValue: DiffInputValue,
  newValue: DiffInputValue,
  status: DiffStatus,
): FieldDiffItem {
  return {
    field: path,
    old_value: toOutputValue(oldValue),
    new_value: toOutputValue(newValue),
    status,
    path,
    is_override: isOverrideDiffStatus(status),
  };
}

function diffPrimitiveValues(
  path: string,
  oldValue: DiffInputValue,
  newValue: DiffInputValue,
) {
  const oldMissing = isEffectivelyMissing(oldValue);
  const newMissing = isEffectivelyMissing(newValue);

  if (oldMissing && newMissing) {
    return [buildDiffItem(path, oldValue, newValue, "unchanged")];
  }

  if (oldMissing) {
    return [buildDiffItem(path, oldValue, newValue, "added")];
  }

  if (newMissing) {
    return [buildDiffItem(path, oldValue, newValue, "removed")];
  }

  const status =
    stableSerialize(oldValue) === stableSerialize(newValue)
      ? "unchanged"
      : "changed";

  return [buildDiffItem(path, oldValue, newValue, status)];
}

function diffObjects(
  path: string,
  oldValue: { [key: string]: DiffInputValue },
  newValue: { [key: string]: DiffInputValue },
) {
  const keys = Array.from(
    new Set([...Object.keys(oldValue), ...Object.keys(newValue)]),
  ).sort((leftKey, rightKey) => leftKey.localeCompare(rightKey));

  if (keys.length === 0) {
    return [buildDiffItem(path, oldValue, newValue, "unchanged")];
  }

  return keys.flatMap((key) =>
    diffValues(getChildPath(path, key), oldValue[key], newValue[key]),
  );
}

function createArrayEntries(values: readonly DiffInputValue[]): ArrayEntry[] {
  return values.map((value, index) => ({
    index,
    key: stableSerialize(value),
    value,
  }));
}

function findReusableArrayEntry(
  oldEntries: readonly ArrayEntry[],
  usedOldIndexes: ReadonlySet<number>,
  key: string,
) {
  return oldEntries.find(
    (entry) => entry.key === key && !usedOldIndexes.has(entry.index),
  );
}

function diffArrays(
  path: string,
  oldValue: readonly DiffInputValue[],
  newValue: readonly DiffInputValue[],
) {
  if (oldValue.length === 0 && newValue.length === 0) {
    return [buildDiffItem(path, oldValue, newValue, "unchanged")];
  }

  const oldEntries = createArrayEntries(oldValue);
  const newEntries = createArrayEntries(newValue);
  const pairsByNewIndex = new Map<number, ArrayPair>();
  const usedOldIndexes = new Set<number>();

  newEntries.forEach((newEntry) => {
    const sameIndexOldEntry = oldEntries[newEntry.index];

    if (
      sameIndexOldEntry?.key === newEntry.key &&
      !usedOldIndexes.has(sameIndexOldEntry.index)
    ) {
      pairsByNewIndex.set(newEntry.index, {
        oldIndex: sameIndexOldEntry.index,
        newIndex: newEntry.index,
        oldValue: sameIndexOldEntry.value,
        newValue: newEntry.value,
      });
      usedOldIndexes.add(sameIndexOldEntry.index);
    }
  });

  newEntries.forEach((newEntry) => {
    if (pairsByNewIndex.has(newEntry.index)) {
      return;
    }

    const matchingOldEntry = findReusableArrayEntry(
      oldEntries,
      usedOldIndexes,
      newEntry.key,
    );

    if (!matchingOldEntry) {
      return;
    }

    pairsByNewIndex.set(newEntry.index, {
      oldIndex: matchingOldEntry.index,
      newIndex: newEntry.index,
      oldValue: matchingOldEntry.value,
      newValue: newEntry.value,
    });
    usedOldIndexes.add(matchingOldEntry.index);
  });

  const diffs = newEntries.map((newEntry) => {
    const pair = pairsByNewIndex.get(newEntry.index);

    if (!pair) {
      return buildDiffItem(
        getArrayPath(path, newEntry.index),
        undefined,
        newEntry.value,
        "added",
      );
    }

    return buildDiffItem(
      getArrayPath(path, newEntry.index),
      pair.oldValue,
      pair.newValue,
      pair.oldIndex === pair.newIndex ? "unchanged" : "reordered",
    );
  });

  oldEntries.forEach((oldEntry) => {
    if (usedOldIndexes.has(oldEntry.index)) {
      return;
    }

    diffs.push(
      buildDiffItem(
        getArrayPath(path, oldEntry.index),
        oldEntry.value,
        undefined,
        "removed",
      ),
    );
  });

  return diffs;
}

function diffValues(
  path: string,
  oldValue: DiffInputValue,
  newValue: DiffInputValue,
): FieldDiffItem[] {
  if (Array.isArray(oldValue) || Array.isArray(newValue)) {
    if (
      (!Array.isArray(oldValue) && !isEffectivelyMissing(oldValue)) ||
      (!Array.isArray(newValue) && !isEffectivelyMissing(newValue))
    ) {
      return [buildDiffItem(path, oldValue, newValue, "changed")];
    }

    return diffArrays(
      path,
      Array.isArray(oldValue) ? oldValue : [],
      Array.isArray(newValue) ? newValue : [],
    );
  }

  if (isDiffObject(oldValue) || isDiffObject(newValue)) {
    if (isDiffObject(oldValue) && isDiffObject(newValue)) {
      return diffObjects(path, oldValue, newValue);
    }

    if (isEffectivelyMissing(oldValue) && isDiffObject(newValue)) {
      return diffObjects(path, {}, newValue);
    }

    if (isDiffObject(oldValue) && isEffectivelyMissing(newValue)) {
      return diffObjects(path, oldValue, {});
    }

    return [buildDiffItem(path, oldValue, newValue, "changed")];
  }

  return diffPrimitiveValues(path, oldValue, newValue);
}

export function buildFieldDiff(
  field: string,
  oldValue: DiffInputValue,
  newValue: DiffInputValue,
) {
  return diffValues(normalizeFieldPath(field), oldValue, newValue);
}

function formatPrimitive(value: DiffPrimitive) {
  return String(value);
}

function formatValue(value: DiffInputValue) {
  const outputValue = toOutputValue(value);

  if (outputValue === null) {
    return "None";
  }

  if (
    typeof outputValue === "string" ||
    typeof outputValue === "number" ||
    typeof outputValue === "boolean"
  ) {
    return formatPrimitive(outputValue);
  }

  if (Array.isArray(outputValue)) {
    if (outputValue.length === 0) {
      return "None";
    }

    const containsOnlyPrimitiveValues = outputValue.every(
      (item) =>
        item === null ||
        typeof item === "string" ||
        typeof item === "number" ||
        typeof item === "boolean",
    );

    if (containsOnlyPrimitiveValues) {
      return outputValue
        .map((item) => (item === null ? "None" : formatPrimitive(item)))
        .join("\n");
    }
  } else if (Object.keys(outputValue).length === 0) {
    return "None";
  }

  return JSON.stringify(outputValue, null, 2);
}

export function FieldDiffViewer({
  aiValue,
  humanValue,
  label,
  field,
  leftLabel = "AI Value",
  overlayLabel,
  overlayValue,
  rightLabel = "Human Value",
}: FieldDiffViewerProps) {
  const diffItems = buildFieldDiff(field ?? label, aiValue, humanValue);
  const summaryStatus = getDiffSummaryStatus(
    diffItems.map((item) => item.status),
  );
  const statusClass = isOverrideDiffStatus(summaryStatus)
    ? "k12-review-diff-changed"
    : "k12-review-diff-same";

  return (
    <section
      aria-label={`${label} ${leftLabel} and ${rightLabel} diff`}
      className={`k12-review-diff ${statusClass}`}
    >
      <header className="k12-review-diff-header">
        <strong>{label}</strong>
        <span>{diffStatusLabels[summaryStatus]}</span>
      </header>

      <div className="k12-review-diff-grid">
        <div>
          <span>{leftLabel}</span>
          <pre>{formatValue(aiValue)}</pre>
        </div>
        <div>
          <span>{rightLabel}</span>
          <pre>{formatValue(humanValue)}</pre>
        </div>
        {overlayLabel && overlayValue !== undefined ? (
          <div style={{ gridColumn: "1 / -1" }}>
            <span>{overlayLabel}</span>
            <pre>{formatValue(overlayValue)}</pre>
          </div>
        ) : null}
        <div style={{ gridColumn: "1 / -1" }}>
          <span>Highlighted Changes</span>
          <ul className="k12-review-diff-items">
            {diffItems.map((item) => (
              <li
                className={`k12-review-diff-item k12-review-diff-item-${item.status}`}
                key={`${item.path}-${item.status}`}
              >
                <span>{diffStatusLabels[item.status]}</span>
                <code>{item.path}</code>
                <strong>
                  {formatValue(item.old_value)} {" -> "}{" "}
                  {formatValue(item.new_value)}
                </strong>
              </li>
            ))}
          </ul>
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <span>Diff Output</span>
          <pre>{JSON.stringify(diffItems, null, 2)}</pre>
        </div>
      </div>
    </section>
  );
}
