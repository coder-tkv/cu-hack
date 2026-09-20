/** Иконки из макета: шеврон 22x12 и папка 25x25, обводка без заливки. */

export function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="22"
      height="12"
      viewBox="0 0 22 12"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M1 1L11 11L21 1"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function FolderIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="25"
      height="25"
      viewBox="0 0 25 25"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M2 6.5C2 5.11929 3.11929 4 4.5 4H9L11.5 7H20.5C21.8807 7 23 8.11929 23 9.5V18.5C23 19.8807 21.8807 21 20.5 21H4.5C3.11929 21 2 19.8807 2 18.5V6.5Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function AlertIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="9" cy="9" r="9" fill="currentColor" />
      <path d="M9 4.5V10" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" />
      <circle cx="9" cy="13" r="1.2" fill="#ffffff" />
    </svg>
  );
}

export function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10" cy="10" r="10" fill="currentColor" />
      <path
        d="M5.5 10.3L8.6 13.4L14.5 6.9"
        stroke="#ffffff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Стрелка «открыть» в углу карточки рекомендации (стр. 4 макета). */
export function ExternalLinkIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M11.5 2.5H17.5V8.5M17.5 2.5L9.5 10.5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M15.5 12.5V16C15.5 16.8284 14.8284 17.5 14 17.5H4C3.17157 17.5 2.5 16.8284 2.5 16V6C2.5 5.17157 3.17157 4.5 4 4.5H7.5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Кавычки вокруг текста рекомендации. */
export function QuoteIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="18"
      height="14"
      viewBox="0 0 18 14"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M7 0.8C3.3 2.2 1 5 1 8.4c0 2.9 1.6 4.8 3.9 4.8 2 0 3.5-1.5 3.5-3.4 0-1.9-1.3-3.2-3-3.2-.3 0-.7 0-1 .1.5-1.7 1.9-3.2 3.9-4.2L7 .8Zm9 0C12.3 2.2 10 5 10 8.4c0 2.9 1.6 4.8 3.9 4.8 2 0 3.5-1.5 3.5-3.4 0-1.9-1.3-3.2-3-3.2-.3 0-.7 0-1 .1.5-1.7 1.9-3.2 3.9-4.2L16 .8Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function SpinnerIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.35" strokeWidth="2" />
      <path
        d="M14.5 8A6.5 6.5 0 0 0 8 1.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
