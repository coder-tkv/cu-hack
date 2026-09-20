import type { ReactNode } from "react";
import { TopBar } from "./TopBar";
import styles from "./Layout.module.css";

type Align = "center" | "top";
type CardSize = "model" | "upload" | "wide";

const cardSizes: Record<CardSize, string> = {
  model: styles.cardModel,
  upload: styles.cardUpload,
  wide: styles.cardWide,
};

/** Общий каркас: верхняя панель + карточка по центру полотна. */
export function Layout({
  children,
  align = "center",
  card = "model",
  topBarAction,
}: {
  children: ReactNode;
  align?: Align;
  card?: CardSize;
  topBarAction?: ReactNode;
}) {
  return (
    <div className={styles.page}>
      <TopBar action={topBarAction} />
      <main
        className={[
          styles.main,
          align === "center" ? styles.mainCentered : styles.mainTop,
          card === "wide" ? styles.mainWide : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <section className={`${styles.card} ${cardSizes[card]}`}>{children}</section>
      </main>
    </div>
  );
}
