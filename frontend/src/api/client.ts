import { API_BASE } from "./config";
import type {
  AnalysisState,
  ApiError,
  Report,
  SessionCreated,
  StepDetail,
  StepsPage,
} from "./types";

/**
 * Ошибка запроса с уже готовым текстом для пользователя.
 * Сырой JSON наружу не показываем никогда.
 */
export class RequestError extends Error {
  readonly status: number;
  readonly apiError: ApiError | null;

  constructor(message: string, status: number, apiError: ApiError | null) {
    super(message);
    this.name = "RequestError";
    this.status = status;
    this.apiError = apiError;
  }
}

function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ApiError).message === "string" &&
    typeof (value as ApiError).code === "string"
  );
}

/** Достаёт detail.message; при неожиданном формате отдаёт «Ошибка {код}». */
export async function toApiError(res: Response): Promise<RequestError> {
  let apiError: ApiError | null = null;
  let message = `Ошибка ${res.status}`;
  try {
    const body: unknown = await res.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (isApiError(detail)) {
      apiError = detail;
      message = detail.message;
    } else if (typeof detail === "string" && detail.trim() !== "") {
      message = detail;
    }
  } catch {
    // тело не JSON — остаётся текст «Ошибка {код}»
  }
  return new RequestError(message, res.status, apiError);
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new RequestError("Не удалось связаться с сервером", 0, null);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

export async function createSession(file: File, llmEnabled: boolean): Promise<SessionCreated> {
  const form = new FormData();
  form.append("file", file);
  form.append("format", "claude_code");
  form.append("llm_enabled", String(llmEnabled));
  // Content-Type не ставим руками: браузер сам добавит boundary.
  return requestJson<SessionCreated>(`${API_BASE}/api/sessions`, {
    method: "POST",
    body: form,
  });
}

export async function getAnalysisState(analysisId: string): Promise<AnalysisState> {
  return requestJson<AnalysisState>(
    `${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}`,
  );
}

export async function getReport(analysisId: string): Promise<Report> {
  return requestJson<Report>(
    `${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/report`,
  );
}

export async function getSteps(
  sessionId: string,
  cursor: string | null = null,
  limit = 50,
): Promise<StepsPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  return requestJson<StepsPage>(
    `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/steps?${params.toString()}`,
  );
}

export async function getStep(sessionId: string, stepId: string): Promise<StepDetail> {
  // step_id содержит двоеточия — кодируем обязательно.
  return requestJson<StepDetail>(
    `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/steps/${encodeURIComponent(stepId)}`,
  );
}

export function artifactUrl(analysisId: string, name: string): string {
  return `${API_BASE}/api/analyses/${encodeURIComponent(analysisId)}/artifacts/${encodeURIComponent(name)}`;
}
