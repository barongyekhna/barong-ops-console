"use client";

import { LoaderCircle, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";

import styles from "./ProductKnowledge.module.css";
import type { ProductFormValues, ProductKnowledgeCreatePayload } from "./types";

const initialValues: ProductFormValues = {
  brand_name: "",
  product_key: "",
  product_name_en: "",
  product_type: "",
  raw_input_language: "en",
  raw_input_text: "",
  sku: "",
};

type ProductFormProps = {
  error: string;
  isSubmitting: boolean;
  onCreate: (payload: ProductKnowledgeCreatePayload) => Promise<void>;
  onDismissError: () => void;
};

function optionalText(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function ProductForm({
  error,
  isSubmitting,
  onCreate,
  onDismissError,
}: ProductFormProps) {
  const [values, setValues] = useState<ProductFormValues>(initialValues);
  const [validationError, setValidationError] = useState("");

  function updateValue(key: keyof ProductFormValues, value: string) {
    setValues((current) => ({ ...current, [key]: value }));
    setValidationError("");
    if (error) {
      onDismissError();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const productKey = values.product_key.trim();
    const rawInputText = values.raw_input_text.trim();
    const rawInputLanguage = values.raw_input_language.trim().toLowerCase();

    if (!productKey || !rawInputText || !rawInputLanguage) {
      setValidationError("Product key, language, and raw input are required.");
      return;
    }

    try {
      await onCreate({
        brand_name: optionalText(values.brand_name),
        canonical_language: rawInputLanguage,
        product_key: productKey,
        product_name_en: optionalText(values.product_name_en),
        product_status: "draft",
        product_type: optionalText(values.product_type),
        raw_input_language: rawInputLanguage,
        raw_input_text: rawInputText,
        review_status: "draft",
        sku: optionalText(values.sku),
        source_system: "manual",
      });
      setValues(initialValues);
    } catch {
      // The parent renders the API error; keep the entered values for retry.
    }
  }

  const formError = validationError || error;

  return (
    <form
      aria-label="Create product knowledge product"
      className={styles.form}
      onSubmit={(event) => void handleSubmit(event)}
    >
      <div className={styles.panelHeading}>
        <div>
          <span className={styles.eyebrow}>Create</span>
          <h3>New Product</h3>
        </div>
        <button
          className="primary-button"
          disabled={isSubmitting}
          type="submit"
        >
          {isSubmitting ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <Plus aria-hidden="true" size={17} />
          )}
          {isSubmitting ? "Creating" : "Create Product"}
        </button>
      </div>

      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span>Product key</span>
          <input
            autoComplete="off"
            onChange={(event) => updateValue("product_key", event.target.value)}
            placeholder="k-product-001"
            required
            value={values.product_key}
          />
        </label>

        <label className={styles.field}>
          <span>Product name</span>
          <input
            autoComplete="off"
            onChange={(event) =>
              updateValue("product_name_en", event.target.value)
            }
            placeholder="Stainless steel pump"
            value={values.product_name_en}
          />
        </label>

        <label className={styles.field}>
          <span>SKU</span>
          <input
            autoComplete="off"
            onChange={(event) => updateValue("sku", event.target.value)}
            placeholder="SKU-1001"
            value={values.sku}
          />
        </label>

        <label className={styles.field}>
          <span>Brand</span>
          <input
            autoComplete="off"
            onChange={(event) => updateValue("brand_name", event.target.value)}
            placeholder="Brand"
            value={values.brand_name}
          />
        </label>

        <label className={styles.field}>
          <span>Product type</span>
          <input
            autoComplete="off"
            onChange={(event) => updateValue("product_type", event.target.value)}
            placeholder="Industrial component"
            value={values.product_type}
          />
        </label>

        <label className={styles.field}>
          <span>Language</span>
          <input
            autoComplete="off"
            maxLength={16}
            onChange={(event) =>
              updateValue("raw_input_language", event.target.value)
            }
            required
            value={values.raw_input_language}
          />
        </label>
      </div>

      <label className={styles.field}>
        <span>Raw input</span>
        <textarea
          onChange={(event) => updateValue("raw_input_text", event.target.value)}
          placeholder="Paste the source product description or notes."
          required
          rows={5}
          value={values.raw_input_text}
        />
      </label>

      <p className={styles.formMessage} role={formError ? "alert" : undefined}>
        {formError}
      </p>
    </form>
  );
}
