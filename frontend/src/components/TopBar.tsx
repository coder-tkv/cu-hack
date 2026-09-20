import { Link } from "react-router-dom";
import { ChevronDownIcon } from "./icons";
import styles from "./TopBar.module.css";

/** Верхняя панель из макета: слева название, справа шеврон — возврат к выбору модели. */
export function TopBar() {
  return (
    <header className={styles.bar}>
      <Link to="/" className={styles.logo}>
        Claude Code
      </Link>
      <Link to="/" className={styles.action} aria-label="Выбрать модель">
        <ChevronDownIcon />
      </Link>
    </header>
  );
}
