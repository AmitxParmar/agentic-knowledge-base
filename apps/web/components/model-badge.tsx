"use client";

import { useModelInfo } from "@/features/research/api/use-model-info";
import styles from "./model-badge.module.css";

export function ModelBadge() {
  const { data, isError, isLoading } = useModelInfo();

  if (isLoading) return <span className={styles.badge}>MODEL …</span>;
  if (isError || !data) return <span className={styles.badge}>MODEL —</span>;

  const primary = data.primary; // e.g. groq/openai/gpt-oss-20b
  const fallback = data.fallback; // e.g. openrouter/mistralai/mistral-7b-instruct

  return (
    <span className={styles.badge} title={`Fallback: ${fallback}\nPrimary hits Groq first; OpenRouter only on Groq failure (LiteLLM fallbacks). Separate quotas.`}>
      <span className={styles.label}>LLM</span>
      <span className={styles.value}>{primary}</span>
      <span className={styles.sep}>→</span>
      <span className={styles.fallback}>{fallback}</span>
    </span>
  );
}
