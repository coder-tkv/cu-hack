import type { Metric } from "../api/types";
import { formatMetricValue } from "../utils/labels";
import styles from "./MetricsSummary.module.css";

/** Карточки метрик. `value === null` — «неизвестно» серым, никогда не «0». */
export function MetricsSummary({ metrics }: { metrics: Metric[] }) {
  if (metrics.length === 0) {
    return <p className={styles.empty}>Метрики не рассчитаны</p>;
  }

  return (
    <div className={styles.grid}>
      {metrics.map((metric) => {
        const { value, unknown } = formatMetricValue(metric);
        return (
          <article key={metric.key} className={styles.card}>
            <h3 className={styles.label}>{metric.label}</h3>
            <p className={`${styles.value} ${unknown ? styles.valueUnknown : ""}`}>{value}</p>
            {unknown && metric.coverage && <p className={styles.note}>{metric.coverage}</p>}
            {!unknown && metric.coverage && <p className={styles.note}>{metric.coverage}</p>}
            {metric.limitations.length > 0 && (
              <ul className={styles.limitations}>
                {metric.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </article>
        );
      })}
    </div>
  );
}
