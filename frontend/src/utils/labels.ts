import type {
  Actor,
  AnalysisStatus,
  Assessment,
  ExplanationSource,
  Metric,
  Severity,
  StepKind,
} from "../api/types";

/** Заголовки групп находок. Неизвестный kind показываем как есть, не падаем. */
const FINDING_KIND_LABELS: Record<string, string> = {
  repeated_tool_call: "Повторные вызовы",
  repeated_failed_tool: "Повторные попытки",
  failure_chain: "Цепочки ошибок",
  human_intervention: "Вмешательства человека",
  reverted_edit: "Откаты правок",
  file_churn: "Перепахивание файлов",
  file_rewrite_loop: "Переписывание по кругу",
  long_gap: "Долгие паузы",
  expensive_segment: "Дорогие участки",
  spend_without_progress: "Расход без результата",
  environment_failure: "Сбои окружения",
  tool_underuse: "Инструменты не по назначению",
  missing_tool: "Инструмента нет в окружении",
  tool_denied: "Доступ к инструменту закрыт",
  unknown: "Прочие находки",
};

export function findingKindLabel(kind: string): string {
  return FINDING_KIND_LABELS[kind] ?? kind;
}

export const SEVERITY_LABELS: Record<Severity, string> = {
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low"];

export function assessmentLabel(assessment: Assessment | null): string {
  if (assessment === "inefficient") return "неэффективно";
  if (assessment === "reasonable") return "обоснованно";
  if (assessment === "uncertain") return "недостаточно данных";
  return "не объяснено";
}

/** Пометка об источнике объяснения: отсутствие объяснения ≠ отсутствие проблемы. */
export function explanationSourceNote(source: ExplanationSource): string | null {
  if (source === "rule_based") return "шаблонное объяснение";
  if (source === "not_explained") return "модель не объясняла этот эпизод";
  return null;
}

export const STATUS_LABELS: Record<AnalysisStatus, string> = {
  queued: "В очереди",
  parsing: "Чтение файла",
  analyzing: "Расчет метрик",
  explaining: "Объяснение находок",
  assembling: "Сбор отчета",
  complete: "Готово",
  partial: "Готово частично",
  insufficient_data: "Мало данных",
  failed: "Ошибка",
  interrupted: "Прервано",
};

export const STEP_KIND_LABELS: Record<StepKind, string> = {
  human_message: "сообщение человека",
  assistant_text: "ответ агента",
  tool_call: "вызов инструмента",
  tool_result: "результат инструмента",
  system_event: "системное событие",
  unknown: "неизвестное событие",
};

export const ACTOR_LABELS: Record<Actor, string> = {
  human: "человек",
  assistant: "агент",
  tool: "инструмент",
  system: "система",
  unknown: "неизвестно",
};

/** Ключи facts переводим по словарю, незнакомые показываем как есть. */
const FACT_LABELS: Record<string, string> = {
  tool: "Инструмент",
  tool_name: "Инструмент",
  command: "Команда",
  argsPreview: "Аргументы",
  repeats: "Повторов",
  errors: "Ошибок",
  attempt_count: "Попыток",
  explicit_error_count: "Явных ошибок",
  identical_errors: "Ошибки одинаковые",
  spanCalls: "Вызовов в эпизоде",
  backToBack: "Подряд без пауз",
  mutatingBetween: "Правок между попытками",
  otherCallsBetween: "Других вызовов между",
  compactionsBetween: "Сжатий контекста между",
  our_type: "Тип детектора",
  file: "Файл",
  files: "Файлов",
  gapSeconds: "Длительность паузы, с",
  totalSeconds: "Всего, с",
  tokens: "Токенов",
  share: "Доля",
};

export function factLabel(key: string): string {
  return FACT_LABELS[key] ?? key;
}

/** Значение facts: примитивы как текст, объекты — компактным JSON. */
export function factValue(value: unknown): string {
  if (value === null || value === undefined) return "неизвестно";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "неизвестно";
  const rounded = Math.abs(value) < 1 ? value : Math.round(value * 100) / 100;
  return rounded.toLocaleString("ru-RU");
}

/** Секунды в человеческий вид: 125 → «2 мин 5 с». */
export function formatSeconds(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total} с`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest === 0 ? `${minutes} мин` : `${minutes} мин ${rest} с`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes === 0 ? `${hours} ч` : `${hours} ч ${restMinutes} мин`;
}

/**
 * Значение метрики для показа. `null` — это «неизвестно», а не ноль.
 * Для долей рядом обязательно знаменатель: «70% (7 из 10)».
 */
export function formatMetricValue(metric: Metric): { value: string; unknown: boolean } {
  if (metric.value === null) return { value: "неизвестно", unknown: true };
  if (metric.unit === "ratio") {
    const percent = `${Math.round(metric.value * 100)}%`;
    if (metric.denominator === null) return { value: percent, unknown: false };
    const part = Math.round(metric.value * metric.denominator);
    return { value: `${percent} (${part} из ${metric.denominator})`, unknown: false };
  }
  if (metric.unit === "seconds") return { value: formatSeconds(metric.value), unknown: false };
  // Бекенд отдаёт ещё minutes и usd — форматируем их по-человечески.
  if (metric.unit === "minutes") return { value: formatSeconds(metric.value * 60), unknown: false };
  if (metric.unit === "usd") {
    return { value: `${metric.value.toFixed(2).replace(".", ",")} $`, unknown: false };
  }
  return { value: formatNumber(metric.value), unknown: false };
}

/** Номер строки исходного файла из step_id вида «s_7d9:line_42:block_0». */
export function lineFromStepId(stepId: string): number | null {
  const match = /:line_(\d+):/.exec(stepId);
  return match ? Number(match[1]) : null;
}

export function stepLabel(stepId: string): string {
  const line = lineFromStepId(stepId);
  return line === null ? "Шаг" : `Строка ${line}`;
}

/** ISO 8601 → «20.09.2026, 12:14». Пустую дату не выдумываем. */
export function formatDateTime(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(iso: string | null): string {
  if (!iso) return "время неизвестно";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "время неизвестно";
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
