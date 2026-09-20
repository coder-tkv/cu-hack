import { useEffect, useState } from "react";
import { getStep } from "../api/client";
import type { Step, StepDetail } from "../api/types";
import { ACTOR_LABELS, STEP_KIND_LABELS, formatTime, lineFromStepId } from "../utils/labels";
import { SpinnerIcon } from "./icons";
import styles from "./EvidenceViewer.module.css";

const PAGE = 8;

/** Аргументы вызова: сначала command, иначе весь объект как JSON. */
function argumentsText(step: Step): string | null {
  if (!step.arguments) return null;
  const command = step.arguments["command"];
  if (typeof command === "string") return command;
  try {
    return JSON.stringify(step.arguments, null, 2);
  } catch {
    return null;
  }
}

function StepRow({ step, muted = false }: { step: Step; muted?: boolean }) {
  const line = step.source.source_line;
  const args = argumentsText(step);
  const errorFrame = step.is_error === true;

  return (
    <article className={`${styles.step} ${muted ? styles.stepMuted : ""}`}>
      <header className={styles.stepHead}>
        <span className={styles.ordinal}>#{step.ordinal}</span>
        <span className={styles.stepKind}>{STEP_KIND_LABELS[step.kind]}</span>
        <span className={styles.stepMeta}>{ACTOR_LABELS[step.actor]}</span>
        <span className={styles.stepMeta}>{formatTime(step.timestamp)}</span>
        <span className={styles.lineTag}>строка {line}</span>
        {step.is_error === true && <span className={styles.errorTag}>ошибка</span>}
        {/* «статус неизвестен» осмысленно только для результата инструмента */}
        {step.kind === "tool_result" && step.is_error === null && (
          <span className={styles.stepMeta}>статус неизвестен</span>
        )}
      </header>

      {step.tool_name && <p className={styles.toolName}>{step.tool_name}</p>}

      {/* Текст лога рендерим только как текст: это недоверенные данные. */}
      {args && <pre className={styles.code}>{args}</pre>}
      {step.text && <pre className={`${styles.code} ${errorFrame ? styles.codeError : ""}`}>{step.text}</pre>}
      {step.text_truncated && <p className={styles.truncated}>вывод обрезан</p>}
    </article>
  );
}

/**
 * Доказательства находки: шаги по evidence_step_ids, по 8 за раз.
 * Соседние шаги показываем приглушённо — они дают контекст.
 */
export function EvidenceViewer({
  sessionId,
  stepIds,
}: {
  sessionId: string;
  stepIds: string[];
}) {
  const [limit, setLimit] = useState(PAGE);
  const [details, setDetails] = useState<Record<string, StepDetail>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const visible = stepIds.slice(0, limit);
  const key = visible.join("|");
  // Идентификаторы уже показанных шагов — чтобы соседи не повторяли доказательства.
  const shown = new Set<string>(visible);

  useEffect(() => {
    let cancelled = false;
    const missing = visible.filter((id) => !(id in details));
    if (missing.length === 0) return;

    setLoading(true);
    setError(null);
    Promise.all(
      missing.map(async (id) => [id, await getStep(sessionId, id)] as const),
    )
      .then((pairs) => {
        if (cancelled) return;
        setDetails((prev) => {
          const next = { ...prev };
          for (const [id, detail] of pairs) next[id] = detail;
          return next;
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Не удалось загрузить шаги");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // details намеренно не в зависимостях: иначе цикл после каждой догрузки
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, key]);

  if (stepIds.length === 0) {
    return <p className={styles.empty}>К этой находке не привязаны шаги лога</p>;
  }

  return (
    <div className={styles.viewer}>
      {visible.map((id) => {
        const detail = details[id];
        // Соседние шаги часто совпадают с другими доказательствами — не дублируем.
        const before = detail?.neighbors_before.slice(-1).filter((s) => !shown.has(s.step_id)) ?? [];
        before.forEach((s) => shown.add(s.step_id));
        if (detail) shown.add(detail.step.step_id);
        const after = detail?.neighbors_after.slice(0, 1).filter((s) => !shown.has(s.step_id)) ?? [];
        after.forEach((s) => shown.add(s.step_id));
        if (!detail) {
          return (
            <div key={id} className={styles.placeholder}>
              <SpinnerIcon className={styles.spinner} />
              <span>Загружаем {lineFromStepId(id) === null ? "шаг" : `строку ${lineFromStepId(id)}`}…</span>
            </div>
          );
        }
        return (
          <div key={id} className={styles.block}>
            {before.map((step) => (
              <StepRow key={step.step_id} step={step} muted />
            ))}
            <StepRow step={detail.step} />
            {after.map((step) => (
              <StepRow key={step.step_id} step={step} muted />
            ))}
          </div>
        );
      })}

      {error && <p className={styles.error}>{error}</p>}

      {limit < stepIds.length && (
        <button
          type="button"
          className={styles.more}
          onClick={() => setLimit((value) => value + PAGE)}
          disabled={loading}
        >
          Показать ещё ({stepIds.length - limit})
        </button>
      )}
    </div>
  );
}
