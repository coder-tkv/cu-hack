import { useCallback, useEffect, useRef, useState } from "react";
import { RequestError, getAnalysisState } from "../api/client";
import type { AnalysisState } from "../api/types";
import { TERMINAL_STATUSES } from "../api/types";

/** Интервал опроса: обработка идёт в фоне на сервере, HTTP сам обновления не присылает. */
const POLL_INTERVAL_MS = 2000;
/** После трёх неудач подряд перестаём долбить сервер и показываем «Повторить». */
const MAX_FAILURES = 3;

export interface AnalysisStatusResult {
  state: AnalysisState | null;
  /** Первый запрос ещё не ответил. */
  loading: boolean;
  /** Опрос спотыкается, но мы продолжаем попытки. */
  connectionLost: boolean;
  /** Три неудачи подряд или фатальная ошибка: нужна кнопка «Повторить». */
  needsRetry: boolean;
  /** Текст ошибки для пользователя. */
  error: string | null;
  retry: () => void;
}

/**
 * Опрашивает статус анализа каждые 2 секунды рекурсивным setTimeout:
 * следующий запрос уходит только после ответа предыдущего, поэтому они не наслаиваются.
 * На терминальном статусе опрос прекращается, таймер чистится при размонтировании.
 */
export function useAnalysisStatus(analysisId: string | undefined): AnalysisStatusResult {
  const [state, setState] = useState<AnalysisState | null>(null);
  const [loading, setLoading] = useState(true);
  const [failures, setFailures] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const failuresRef = useRef(0);

  const retry = useCallback(() => {
    failuresRef.current = 0;
    setFailures(0);
    setError(null);
    setFatal(false);
    setLoading(true);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!analysisId) return;

    let cancelled = false;
    let timer: number | undefined;

    async function tick() {
      try {
        const next = await getAnalysisState(analysisId!);
        if (cancelled) return;
        failuresRef.current = 0;
        setFailures(0);
        setError(null);
        setState(next);
        setLoading(false);
        if (TERMINAL_STATUSES.includes(next.status)) return; // дальше опрашивать нечего
        timer = window.setTimeout(tick, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        setLoading(false);
        const message = err instanceof Error ? err.message : "Не удалось получить статус";
        setError(message);
        // 404 и прочие ответы сервера повторять бессмысленно.
        if (err instanceof RequestError && err.status >= 400) {
          setFatal(true);
          return;
        }
        failuresRef.current += 1;
        setFailures(failuresRef.current);
        if (failuresRef.current >= MAX_FAILURES) return;
        timer = window.setTimeout(tick, POLL_INTERVAL_MS);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [analysisId, attempt]);

  return {
    state,
    loading,
    connectionLost: !fatal && failures > 0 && failures < MAX_FAILURES,
    needsRetry: fatal || failures >= MAX_FAILURES,
    error,
    retry,
  };
}
