import type { AnalysisStatus } from "../api/types";
import { STATUS_LABELS } from "../utils/labels";
import styles from "./StatusBadge.module.css";

const TONES: Partial<Record<AnalysisStatus, string>> = {
  complete: styles.ok,
  partial: styles.warn,
  insufficient_data: styles.warn,
  failed: styles.danger,
  interrupted: styles.danger,
};

/** Бейдж статуса отчёта из шапки. */
export function StatusBadge({ status }: { status: AnalysisStatus }) {
  return (
    <span className={`${styles.badge} ${TONES[status] ?? styles.neutral}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}
