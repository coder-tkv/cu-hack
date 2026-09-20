// --- Статусы -------------------------------------------------------------
export type AnalysisStatus =
  | "queued" // в очереди
  | "parsing" // чтение файла
  | "analyzing" // метрики и поиск кандидатов
  | "explaining" // объяснение моделью
  | "assembling" // сборка отчёта
  | "complete" // готово полностью
  | "partial" // готово частично (например, LLM отвалилась)
  | "insufficient_data" // записей мало для содержательного разбора
  | "failed" // обработать не удалось
  | "interrupted"; // процесс прервался (рестарт сервера)

// Терминальные: на них прекращаем опрос статуса.
export const TERMINAL_STATUSES: AnalysisStatus[] = [
  "complete",
  "partial",
  "insufficient_data",
  "failed",
  "interrupted",
];

export type Severity = "high" | "medium" | "low";
export type Assessment = "inefficient" | "reasonable" | "uncertain";
export type ExplanationSource = "llm" | "rule_based" | "not_explained";
export type EvidenceStrength = "direct" | "indirect" | "weak";
export type StepKind =
  | "human_message"
  | "assistant_text"
  | "tool_call"
  | "tool_result"
  | "system_event"
  | "unknown";
export type Actor = "human" | "assistant" | "tool" | "system" | "unknown";

// --- POST /api/sessions --------------------------------------------------
export interface SessionCreated {
  session_id: string;
  analysis_id: string;
  status_url: string; // например "/api/analyses/a_123"
}

// --- GET /api/analyses/{id} ---------------------------------------------
export interface Progress {
  stage: AnalysisStatus;
  stage_label: string; // готовая подпись по-русски, показывай её как есть
  percent: number | null; // null = знаменатель неизвестен, полосу не рисуем
  done: number | null;
  total: number | null;
}

export interface AnalysisState {
  analysis_id: string;
  session_id: string;
  status: AnalysisStatus;
  progress: Progress;
  report_available: boolean; // true -> можно идти на /report
  warnings: string[];
  error: string | null; // заполнено только при failed
  created_at: string | null; // ISO 8601
  updated_at: string | null;
}

// --- GET /api/analyses/{id}/report --------------------------------------
export interface Metric {
  key: string;
  label: string; // подпись для UI, уже по-русски
  value: number | null; // null -> показать «неизвестно», НЕ 0
  unit: string | null; // "count" | "ratio" | "tokens" | "seconds"
  denominator: number | null; // знаменатель доли
  coverage: string | null; // на каких данных посчитано
  limitations: string[];
}

export interface Coverage {
  total_lines: number;
  recognized_steps: number;
  invalid_lines: number;
  unknown_events: number;
  candidates_total: number;
  candidates_explained: number;
  llm_enabled: boolean;
  incomplete_reasons: string[];
}

export interface Provenance {
  parser_version: string | null;
  detector_version: string | null;
  prompt_version: string | null;
  model: string | null; // null = модель не вызывалась
}

export interface Finding {
  finding_id: string;
  candidate_id: string;
  kind: string; // "repeated_failed_tool" | "failure_chain" | ...
  title: string; // готовый заголовок карточки
  severity: Severity;
  rank: number; // 0 = самое важное
  facts: Record<string, unknown>; // числа, посчитанные кодом
  evidence_step_ids: string[]; // ссылки на шаги-доказательства
  evidence_strength: EvidenceStrength;
  assessment: Assessment | null; // null = объяснения нет
  explanation: string | null;
  likely_cause: string | null; // всегда предположение, подавай как гипотезу
  explanation_source: ExplanationSource;
  limitations: string[];
  detector_version: string | null;
}

export interface Recommendation {
  recommendation_id: string;
  finding_id: string; // связь с находкой
  action: string;
  rationale: string;
  verification: string | null;
  rule_text: string | null;
  source: ExplanationSource;
}

export interface Report {
  schema_version: string;
  analysis_id: string;
  session_id: string;
  status: AnalysisStatus;
  summary: string;
  coverage: Coverage;
  metrics: Metric[];
  findings: Finding[]; // УЖЕ отсортированы по rank, не сортируй заново
  recommendations: Recommendation[];
  warnings: string[];
  provenance: Provenance;
  artifacts: string[]; // "report.md" | "report.json" | "CLAUDE.generated.md"
  created_at: string | null;
}

// --- Шаги ---------------------------------------------------------------
export interface SourceRef {
  source_line: number; // номер строки в исходном файле
  block_index: number;
  source_event_id: string | null;
  source_message_id: string | null;
}

export interface Step {
  step_id: string; // "s_7d9:line_42:block_0"
  session_id: string;
  ordinal: number; // сквозная нумерация с 0
  source: SourceRef;
  parent_event_id: string | null;
  branch_id: string;
  timestamp: string | null;
  kind: StepKind;
  actor: Actor;
  tool_call_id: string | null;
  tool_name: string | null;
  arguments: Record<string, unknown> | null;
  text: string | null;
  text_truncated: boolean;
  is_error: boolean | null; // null = статус неизвестен, НЕ «успех»
  usage_ref: string | null;
  warnings: string[];
}

export interface StepDetail {
  step: Step;
  tool_call: unknown | null;
  neighbors_before: Step[];
  neighbors_after: Step[];
}

export interface StepsPage {
  items: Step[];
  next_cursor: string | null; // null = страниц больше нет
  total: number | null;
}

// --- Ошибки -------------------------------------------------------------
// Приходит в теле как { "detail": ApiError }
export interface ApiError {
  code: string; // "file_too_large" | "empty_file" | "report_not_ready" | "not_found" | ...
  message: string; // готовый текст по-русски, показывай его пользователю
  status: AnalysisStatus | null;
  status_url: string | null;
}
