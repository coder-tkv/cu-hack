import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronDownIcon } from "./icons";
import styles from "./TopBar.module.css";

/**
 * Верхняя панель из макета: слева название, справа шеврон — возврат к выбору модели.
 * На экране находок вместо шеврона стоит кнопка «Новый анализ» (стр. 4 макета).
 */
export function TopBar({ action }: { action?: ReactNode }) {
  return (
    <header className={styles.bar}>
      <Link to="/" className={styles.logo}>
        Claude Code
      </Link>
      {action ?? (
        <Link to="/" className={styles.action} aria-label="Выбрать модель">
          <ChevronDownIcon />
        </Link>
      )}
    </header>
  );
}
