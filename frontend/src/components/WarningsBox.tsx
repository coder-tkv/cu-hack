import { AlertIcon } from "./icons";
import styles from "./WarningsBox.module.css";

/** Предупреждения приходят ещё до конца обработки — показываем по мере поступления. */
export function WarningsBox({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;

  return (
    <section className={styles.box}>
      <h2 className={styles.title}>Предупреждения</h2>
      <ul className={styles.list}>
        {warnings.map((warning, index) => (
          <li key={`${index}-${warning}`} className={styles.item}>
            <AlertIcon className={styles.icon} />
            <span>{warning}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
