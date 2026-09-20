import type { ReactNode } from "react";
import { TopBar } from "./TopBar";
import styles from "./Layout.module.css";

type Align = "center" | "top";
type CardSize = "model" | "upload";

const cardSizes: Record<CardSize, string> = {
  model: styles.cardModel,
  upload: styles.cardUpload,
};

/** Общий каркас: верхняя панель + карточка по центру полотна. */
export function Layout({
  children,
  align = "center",
  card = "model",
}: {
  children: ReactNode;
  align?: Align;
  card?: CardSize;
}) {
  return (
    <div className={styles.page}>
      <TopBar />
      <main
        className={`${styles.main} ${align === "center" ? styles.mainCentered : styles.mainTop}`}
      >
        <section className={`${styles.card} ${cardSizes[card]}`}>{children}</section>
      </main>
    </div>
  );
}
