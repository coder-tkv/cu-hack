import { useNavigate, useParams } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Button } from "../components/Button";
import styles from "./AnalysisPage.module.css";

/**
 * Заглушка экрана статуса (стр. 3 макета) — он в следующей итерации.
 * Сейчас подтверждает, что файл принят и анализ поставлен в очередь.
 */
export function AnalysisPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const navigate = useNavigate();

  return (
    <Layout align="center" card="model">
      <h1 className={styles.title}>Файл принят, анализ запущен</h1>
      <p className={styles.subtitle}>
        Экран обработки со стадиями и прогрессом делаем следующим шагом.
      </p>
      <p className={styles.row}>
        Идентификатор анализа: <span className={styles.value}>{analysisId}</span>
      </p>
      <div className={styles.actions}>
        <Button onClick={() => navigate("/upload")}>Загрузить другой файл</Button>
      </div>
    </Layout>
  );
}
