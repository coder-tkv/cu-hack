/** Человеческий размер файла: 1 234 567 → «1,2 МБ». */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1).replace(".", ",")} КБ`;
  const mb = kb / 1024;
  return `${mb.toFixed(1).replace(".", ",")} МБ`;
}
