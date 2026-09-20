import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Button } from "../components/Button";
import { StageList } from "../components/StageList";
import { WarningsBox } from "../components/WarningsBox";
import { AlertIcon } from "../components/icons";
import { useAnalysisStatus } from "../hooks/useAnalysisStatus";
import styles from "./AnalysisPage.module.css";

/** Экран 3 (стр. 3 макета): статус обработки со стадиями, прогрессом и предупреждениями. */
export function AnalysisPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const navigate = useNavigate();
  const { state, loading, connectionLost, needsRetry, error, retry } =
    useAnalysisStatus(analysisId);

  const reportAvailable = state?.report_available ?? false;
  const status = state?.status;
  // Отчёт готов — сразу уводим на него, как только он появился.
  const autoRedirect = reportAvailable && (status === "complete" || status === "partial");

  useEffect(() => {
    if (autoRedirect) navigate(`/analyses/${analysisId}/report`, { replace: true });
  }, [autoRedirect, analysisId, navigate]);

  const running =
    status === undefined ||
    status === "queued" ||
    status === "parsing" ||
    status === "analyzing" ||
    status === "explaining" ||
    status === "assembling";

  return (
    <Layout align="top" card="upload">
      <div className={styles.header}>
        <h1 className={styles.title}>Обрабатываем информацию</h1>
        {running && (
          <button type="button" className={styles.cancel} onClick={() => navigate("/upload")}>
            Отменить
          </button>
        )}
      </div>
      <p className={styles.subtitle}>Найдем повторные действия, ошибки, потери токенов</p>

      {loading && (
        <div className={styles.skeletonList} aria-label="Загружаем статус" aria-busy="true">
          <div className={styles.skeletonRow} />
          <div className={styles.skeletonRow} />
          <div className={styles.skeletonRow} />
          <div className={styles.skeletonRow} />
        </div>
      )}

      {state && (
        <div className={styles.stages}>
          <StageList status={state.status} progress={state.progress} />
        </div>
      )}

      {state && <WarningsBox warnings={state.warnings} />}

      {connectionLost && (
        <p className={styles.message}>
          <AlertIcon className={styles.messageIcon} />
          <span>Соединение потеряно, пробуем ещё</span>
        </p>
      )}

      {needsRetry && (
        <p className={`${styles.message} ${styles.messageDanger}`} role="alert">
          <AlertIcon className={styles.messageIcon} />
          <span>
            <span className={styles.messageTitle}>Не удалось получить статус</span>
            <span className={styles.messageText}>{error}</span>
          </span>
        </p>
      )}

      {status === "insufficient_data" && (
        <p className={styles.message}>
          <AlertIcon className={styles.messageIcon} />
          <span>В файле недостаточно записей для содержательного разбора</span>
        </p>
      )}

      {status === "failed" && (
        <p className={`${styles.message} ${styles.messageDanger}`} role="alert">
          <AlertIcon className={styles.messageIcon} />
          <span>
            <span className={styles.messageTitle}>Обработать файл не удалось</span>
            <span className={styles.messageText}>{state?.error ?? "Причина неизвестна"}</span>
          </span>
        </p>
      )}

      {status === "interrupted" && (
        <p className={`${styles.message} ${styles.messageDanger}`} role="alert">
          <AlertIcon className={styles.messageIcon} />
          <span>Обработка прервалась, запустите анализ заново</span>
        </p>
      )}

      {(needsRetry ||
        status === "insufficient_data" ||
        status === "failed" ||
        status === "interrupted") && (
        <div className={styles.actions}>
          {needsRetry && <Button onClick={retry}>Повторить</Button>}
          {status === "insufficient_data" && reportAvailable && (
            <Button onClick={() => navigate(`/analyses/${analysisId}/report`)}>
              Открыть отчёт
            </Button>
          )}
          {!needsRetry && (
            <Button
              variant={status === "insufficient_data" && reportAvailable ? "soft" : "primary"}
              onClick={() => navigate("/upload")}
            >
              Загрузить другой файл
            </Button>
          )}
        </div>
      )}
    </Layout>
  );
}
