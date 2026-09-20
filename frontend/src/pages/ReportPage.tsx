import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Button } from "../components/Button";
import { FindingCard } from "../components/FindingCard";
import { MetricsSummary } from "../components/MetricsSummary";
import { StatusBadge } from "../components/StatusBadge";
import { AlertIcon, ChevronDownIcon } from "../components/icons";
import { RequestError, artifactUrl, getReport } from "../api/client";
import type { Finding, Report, Severity } from "../api/types";
import {
  SEVERITY_LABELS,
  SEVERITY_ORDER,
  findingKindLabel,
  formatDateTime,
} from "../utils/labels";
import styles from "./ReportPage.module.css";

const ARTIFACT_LABELS: Record<string, string> = {
  "report.md": "Отчёт в Markdown",
  "report.json": "Данные отчёта (JSON)",
  "CLAUDE.generated.md": "Предлагаемые правила для проекта",
};

type Filter = "all" | Severity;

/** Группы находок по виду; порядок групп и находок внутри — как отдал бекенд (rank). */
function groupByKind(findings: Finding[]): { kind: string; items: Finding[] }[] {
  const groups: { kind: string; items: Finding[] }[] = [];
  for (const finding of findings) {
    const group = groups.find((item) => item.kind === finding.kind);
    if (group) group.items.push(finding);
    else groups.push({ kind: finding.kind, items: [finding] });
  }
  return groups;
}

export function ReportPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [downloadsOpen, setDownloadsOpen] = useState(false);
  const downloadsRef = useRef<HTMLDivElement | null>(null);

  // Повтор после ошибки: состояние сбрасываем в обработчике клика, а не в эффекте.
  const retry = useCallback(() => {
    setLoading(true);
    setError(null);
    setReport(null);
    setReloadKey((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!analysisId) return;
    let cancelled = false;

    getReport(analysisId)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // 409 — отчёт ещё не готов: молча возвращаем на экран статуса.
        if (err instanceof RequestError && err.status === 409) {
          navigate(`/analyses/${analysisId}`, { replace: true });
          return;
        }
        setError(err instanceof Error ? err.message : "Не удалось загрузить отчёт");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [analysisId, navigate, reloadKey]);

  // Меню скачивания закрываем по клику мимо и по Escape.
  useEffect(() => {
    if (!downloadsOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!downloadsRef.current?.contains(event.target as Node)) setDownloadsOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDownloadsOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [downloadsOpen]);

  const counts = useMemo(() => {
    const result: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
    for (const finding of report?.findings ?? []) result[finding.severity] += 1;
    return result;
  }, [report]);

  const groups = useMemo(() => {
    const findings = report?.findings ?? [];
    const filtered = filter === "all" ? findings : findings.filter((f) => f.severity === filter);
    return groupByKind(filtered);
  }, [report, filter]);

  const newAnalysis = (
    <button type="button" className={styles.topAction} onClick={() => navigate("/upload")}>
      Новый анализ
    </button>
  );

  if (loading) {
    return (
      <Layout align="top" card="wide" topBarAction={newAnalysis}>
        <div className={styles.header}>
          <h1 className={styles.title}>Находки</h1>
        </div>
        <div className={styles.skeletonList} aria-busy="true" aria-label="Загружаем отчёт">
          <div className={styles.skeletonGroup} />
          <div className={styles.skeletonGroup} />
        </div>
      </Layout>
    );
  }

  if (error || !report) {
    return (
      <Layout align="top" card="wide" topBarAction={newAnalysis}>
        <div className={styles.header}>
          <h1 className={styles.title}>Находки</h1>
        </div>
        <section className={styles.group}>
          <p className={styles.errorText} role="alert">
            <AlertIcon className={styles.errorIcon} />
            <span>{error ?? "Отчёт недоступен"}</span>
          </p>
          <div className={styles.errorActions}>
            <Button onClick={retry}>Повторить</Button>
            <Button variant="soft" onClick={() => navigate("/upload")}>
              Загрузить другой файл
            </Button>
          </div>
        </section>
      </Layout>
    );
  }

  const created = formatDateTime(report.created_at);
  const coverage = report.coverage;

  return (
    <Layout align="top" card="wide" topBarAction={newAnalysis}>
      <div className={styles.header}>
        <h1 className={styles.title}>Находки</h1>

        <div className={styles.filters} role="group" aria-label="Фильтр находок по важности">
          <button
            type="button"
            className={`${styles.chip} ${filter === "all" ? styles.chipActive : ""}`}
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            Все типы
          </button>
          {SEVERITY_ORDER.map((severity) => (
            <button
              key={severity}
              type="button"
              className={`${styles.chip} ${filter === severity ? styles.chipActive : ""}`}
              aria-pressed={filter === severity}
              onClick={() => setFilter(filter === severity ? "all" : severity)}
            >
              <span className={`${styles.dot} ${styles[`dot_${severity}`]}`} />
              {SEVERITY_LABELS[severity]}
              <span className={styles.chipCount}>{counts[severity]}</span>
            </button>
          ))}
        </div>

        {report.artifacts.length > 0 && (
          <div className={styles.downloads} ref={downloadsRef}>
            <button
              type="button"
              className={styles.download}
              aria-expanded={downloadsOpen}
              onClick={() => setDownloadsOpen((value) => !value)}
            >
              Скачать отчет
              <ChevronDownIcon className={styles.downloadIcon} />
            </button>
            {downloadsOpen && (
              <div className={styles.downloadMenu}>
                {report.artifacts.map((name) => (
                  <a
                    key={name}
                    className={styles.downloadItem}
                    href={artifactUrl(report.analysis_id, name)}
                    download
                  >
                    {ARTIFACT_LABELS[name] ?? name}
                  </a>
                ))}
                <p className={styles.downloadNote}>
                  Правила просмотрите и перенесите в свой CLAUDE.md вручную.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      <section className={`${styles.group} ${styles.summaryGroup}`}>
        <div className={styles.summaryHead}>
          <StatusBadge status={report.status} />
          {created && <span className={styles.summaryMeta}>Отчёт от {created}</span>}
          <span className={styles.summaryMeta}>Сессия {report.session_id}</span>
        </div>
        <p className={styles.summaryText}>{report.summary}</p>
        {report.status === "partial" && coverage.incomplete_reasons.length > 0 && (
          <div className={styles.partial}>
            {/* Причины тут разные: и пропуски детекторов, и неполный разбор моделью.
                Заголовок не должен валить всё на LLM — отчёт при этом рабочий. */}
            <p className={styles.partialTitle}>Разбор неполный</p>
            <ul className={styles.plainList}>
              {coverage.incomplete_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {groups.length === 0 && (
        <section className={styles.group}>
          <p className={styles.emptyTitle}>
            {report.findings.length === 0
              ? "Значимых проблем не найдено"
              : "По этому фильтру находок нет"}
          </p>
          <p className={styles.emptyText}>
            {report.findings.length === 0
              ? "Сессия разобрана, признаков неэффективной работы в доступных данных нет."
              : "Выберите «Все типы», чтобы увидеть остальные находки."}
          </p>
        </section>
      )}

      {groups.map((group) => (
        <section key={group.kind} className={styles.group}>
          <header className={styles.groupHead}>
            <span className={`${styles.dot} ${styles[`dot_${group.items[0].severity}`]}`} />
            <h2 className={styles.groupTitle}>{findingKindLabel(group.kind)}</h2>
            <span className={styles.groupCount}>{group.items.length}</span>
          </header>
          <div className={styles.rows}>
            {group.items.map((finding) => (
              <FindingCard
                key={finding.finding_id}
                finding={finding}
                sessionId={report.session_id}
                recommendations={report.recommendations.filter(
                  (rec) => rec.finding_id === finding.finding_id,
                )}
              />
            ))}
          </div>
        </section>
      ))}

      <section className={styles.group}>
        <h2 className={styles.sectionTitle}>Полнота анализа</h2>
        <div className={styles.coverage}>
          <div className={styles.coverageItem}>
            <span className={styles.coverageValue}>{coverage.recognized_steps}</span>
            <span className={styles.coverageLabel}>распознано шагов</span>
          </div>
          <div className={styles.coverageItem}>
            <span className={styles.coverageValue}>{coverage.total_lines}</span>
            <span className={styles.coverageLabel}>строк в файле</span>
          </div>
          <div className={styles.coverageItem}>
            <span className={styles.coverageValue}>{coverage.invalid_lines}</span>
            <span className={styles.coverageLabel}>битых строк</span>
          </div>
          <div className={styles.coverageItem}>
            <span className={styles.coverageValue}>{coverage.unknown_events}</span>
            <span className={styles.coverageLabel}>неизвестных событий</span>
          </div>
          <div className={styles.coverageItem}>
            <span className={styles.coverageValue}>
              {coverage.candidates_explained} из {coverage.candidates_total}
            </span>
            <span className={styles.coverageLabel}>кандидатов объяснено</span>
          </div>
        </div>
        {!coverage.llm_enabled && (
          <p className={styles.footnote}>Анализ выполнен без модели, только по правилам</p>
        )}
        {coverage.incomplete_reasons.length > 0 && report.status !== "partial" && (
          <ul className={styles.plainList}>
            {coverage.incomplete_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.group}>
        <h2 className={styles.sectionTitle}>Метрики</h2>
        <MetricsSummary metrics={report.metrics} />
      </section>

      {report.artifacts.length > 0 && (
        <section className={styles.group}>
          <h2 className={styles.sectionTitle}>Файлы отчёта</h2>
          <div className={styles.artifacts}>
            {report.artifacts.map((name) => (
              <a
                key={name}
                className={styles.artifact}
                href={artifactUrl(report.analysis_id, name)}
                download
              >
                {ARTIFACT_LABELS[name] ?? name}
              </a>
            ))}
          </div>
          <p className={styles.footnote}>
            Правила нужно просмотреть и перенести в свой CLAUDE.md вручную.
          </p>
        </section>
      )}

      {report.warnings.length > 0 && (
        <section className={styles.group}>
          <h2 className={styles.sectionTitle}>Предупреждения</h2>
          <ul className={styles.plainList}>
            {report.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      )}

      <p className={styles.provenance}>
        Парсер: {report.provenance.parser_version ?? "неизвестно"} · Детекторы:{" "}
        {report.provenance.detector_version ?? "неизвестно"} · Промпт:{" "}
        {report.provenance.prompt_version ?? "неизвестно"} ·{" "}
        {report.provenance.model === null
          ? "модель не вызывалась"
          : `Модель: ${report.provenance.model}`}
      </p>
    </Layout>
  );
}
