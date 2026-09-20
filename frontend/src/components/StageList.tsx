import { CheckIcon } from "./icons";
import type { AnalysisStatus, Progress } from "../api/types";
import styles from "./StageList.module.css";

/**
 * Стадии в порядке пайплайна бекенда: parsing → analyzing → explaining → assembling.
 * Подписи коротких названий — из макета, подпись активной стадии берём из API как есть.
 */
const STAGES: { stage: AnalysisStatus; title: string }[] = [
  { stage: "parsing", title: "Чтение файла" },
  { stage: "analyzing", title: "Расчёт метрик" },
  { stage: "explaining", title: "Объяснение находок" },
  { stage: "assembling", title: "Сбор отчёта" },
];

const DONE_STATUSES: AnalysisStatus[] = ["complete", "partial", "insufficient_data"];
const BROKEN_STATUSES: AnalysisStatus[] = ["failed", "interrupted"];

type StageState = "done" | "active" | "pending" | "broken";

function stageStates(status: AnalysisStatus, progress: Progress): StageState[] {
  if (DONE_STATUSES.includes(status)) return STAGES.map(() => "done");

  const current = STAGES.findIndex((item) => item.stage === progress.stage);
  const broken = BROKEN_STATUSES.includes(status);
  // queued в список стадий не входит, но файл уже принят и работа началась:
  // держим первую строку активной, иначе экран замирает без признаков жизни.
  // Подпись берётся из stage_label и честно говорит «В очереди».
  const activeIndex = current !== -1 ? current : status === "queued" ? 0 : -1;

  return STAGES.map((_, index) => {
    if (activeIndex === -1) return "pending";
    if (index < activeIndex) return "done";
    if (index > activeIndex) return "pending";
    return broken ? "broken" : "active";
  });
}

export function StageList({ status, progress }: { status: AnalysisStatus; progress: Progress }) {
  const states = stageStates(status, progress);
  const hasCounter = progress.done !== null && progress.total !== null;
  // percent === 0 — это «стадия только стартовала», а не измеренный ноль. Полоса
  // нулевой ширины неотличима от зависшего экрана, поэтому такой случай —
  // тоже неопределённый индикатор.
  const hasMeasurableProgress = progress.percent !== null && progress.percent > 0;

  return (
    <ol className={styles.list}>
      {STAGES.map((item, index) => {
        const state = states[index];
        const isActive = state === "active" || state === "broken";
        // Для активной стадии показываем подпись бекенда как есть.
        const title = isActive ? progress.stage_label : item.title;

        return (
          <li key={item.stage} className={styles.stage}>
            {state === "done" ? (
              <CheckIcon className={`${styles.dot} ${styles.dotDone}`} />
            ) : (
              <span
                className={[
                  styles.dot,
                  state === "active" ? styles.dotActive : "",
                  state === "broken" ? styles.dotError : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                aria-hidden="true"
              />
            )}

            <div className={styles.body}>
              <div className={styles.head}>
                <span className={styles.title}>{title}</span>
                {isActive && hasCounter && (
                  <span className={styles.meta}>
                    {progress.done} из {progress.total}
                  </span>
                )}
              </div>
              {state === "pending" && <p className={styles.note}>В очереди</p>}
            </div>

            <div className={styles.track}>
              {state === "done" && <div className={`${styles.fill} ${styles.fillDone}`} />}
              {state === "active" &&
                (hasMeasurableProgress ? (
                  <div className={styles.fill} style={{ width: `${progress.percent}%` }} />
                ) : (
                  <div className={`${styles.fill} ${styles.fillIndeterminate}`} />
                ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
