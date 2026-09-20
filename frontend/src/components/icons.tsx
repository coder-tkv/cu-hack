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
      <path
        d="M9 4.5V10"
        stroke="#141326"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="9" cy="13" r="1.2" fill="#141326" />
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
