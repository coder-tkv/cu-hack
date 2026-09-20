import type { ButtonHTMLAttributes, ReactNode } from "react";
import { SpinnerIcon } from "./icons";
import styles from "./Button.module.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "soft";
  size?: "medium" | "large";
  loading?: boolean;
  children: ReactNode;
};

export function Button({
  variant = "primary",
  size = "medium",
  loading = false,
  disabled,
  children,
  className,
  ...rest
}: Props) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[styles.button, styles[variant], styles[size], className]
        .filter(Boolean)
        .join(" ")}
    >
      {loading && <SpinnerIcon className={styles.spinner} />}
      {children}
    </button>
  );
}
