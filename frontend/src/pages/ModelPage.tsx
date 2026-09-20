import { useNavigate } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Button } from "../components/Button";
import { ChevronDownIcon } from "../components/icons";
import styles from "./ModelPage.module.css";

/**
 * Экран 1 (стр. 1 макета): выбор модели, лог которой будем разбирать.
 * Бекенд принимает единственный формат лога — claude_code, поэтому в списке один пункт.
 */
export function ModelPage() {
  const navigate = useNavigate();

  return (
    <Layout align="center" card="model">
      <h1 className={styles.title} id="model-title">
        Выберите модель
      </h1>

      <div className={styles.selectWrap}>
        <select
          className={styles.select}
          defaultValue="claude_code"
          aria-labelledby="model-title"
        >
          <option value="claude_code">Claude Code</option>
        </select>
        <ChevronDownIcon className={styles.chevron} />
      </div>

      <div className={styles.actions}>
        <Button size="large" onClick={() => navigate("/upload")}>
          Далее
        </Button>
      </div>
    </Layout>
  );
}
