import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Button } from "../components/Button";
import { RequestError, artifactUrl, getReport } from "../api/client";
import type { Report } from "../api/types";
import styles from "./ReportPage.module.css";

const ARTIFACT_LABELS: Record<string, string> = {
  "report.md": "Отчёт в Markdown",
  "report.json": "Данные отчёта (JSON)",
  "CLAUDE.generated.md": "Предлагаемые правила для проекта",
};

/**
 * Экран 4 (макета пока нет): короткая шапка отчёта и скачивание артефактов.
 * Полная вёрстка отчёта — следующая итерация.
 */
export function ReportPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysisId) return;
    let cancelled = false;

    getReport(analysisId)
      .then((data) => {
        if (!cancelled) setReport(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // 409 = пользователь пришёл слишком рано, возвращаем на экран статуса.
        if (err instanceof RequestError && err.status === 409) {
          navigate(`/analyses/${analysisId}`, { replace: true });
          return;
        }
        setError(err instanceof Error ? err.message : "Не удалось загрузить отчёт");
      });

    return () => {
      cancelled = true;
    };
  }, [analysisId, navigate]);

  return (
    <Layout align="top" card="upload">
      <h1 className={styles.title}>Отчёт готов</h1>
      <p className={styles.summary}>{error ?? report?.summary ?? "Загружаем отчёт…"}</p>

      {report && (
        <>
          <p className={styles.note}>
            Полный экран отчёта — метрики, находки и доказательства — делаем следующим шагом.
            Файлы уже можно скачать.
          </p>
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
        </>
      )}

      <div className={styles.actions}>
        <Button onClick={() => navigate("/upload")}>Загрузить другой файл</Button>
      </div>
    </Layout>
  );
}
