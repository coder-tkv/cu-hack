import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Button } from "../components/Button";
import { AlertIcon, FolderIcon } from "../components/icons";
import { createSession } from "../api/client";
import { MAX_FILE_BYTES } from "../api/config";
import { formatBytes } from "../utils/format";
import styles from "./UploadPage.module.css";

const LOG_PATH = "~/.claude/projects/<проект>/<uuid>.jsonl";

/** Экран 2 (стр. 2 макета): выбор файла лога и запуск анализа. */
export function UploadPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const submittingRef = useRef(false);

  const [file, setFile] = useState<File | null>(null);
  const [llmEnabled, setLlmEnabled] = useState(true);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileWarning, setFileWarning] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function acceptFile(next: File | null) {
    setError(null);
    setFileWarning(null);
    if (!next) return;

    if (next.size === 0) {
      setFile(null);
      setError("Файл пустой — выберите лог сессии с записями.");
      return;
    }
    if (next.size > MAX_FILE_BYTES) {
      setFile(null);
      setError(
        `Файл больше 50 МБ (${formatBytes(next.size)}). Загрузите лог поменьше или разбейте его.`,
      );
      return;
    }
    if (!next.name.toLowerCase().endsWith(".jsonl")) {
      // Не блокируем: судья может принести файл без расширения.
      setFileWarning(
        `Расширение файла не .jsonl. Если внутри лог Claude Code в формате JSONL — всё сработает, иначе сервер вернёт ошибку.`,
      );
    }
    setFile(next);
  }

  function onInputChange(event: ChangeEvent<HTMLInputElement>) {
    acceptFile(event.target.files?.[0] ?? null);
    // Сбрасываем значение, чтобы повторный выбор того же файла тоже сработал.
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    acceptFile(event.dataTransfer.files?.[0] ?? null);
  }

  async function onSubmit() {
    if (!file || submittingRef.current) return; // повторный клик не шлёт второй запрос
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createSession(file, llmEnabled);
      navigate(`/analyses/${created.analysis_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отправить файл");
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  return (
    <Layout align="top" card="upload">
      <h1 className={styles.title}>Загрузите лог сессии</h1>
      <p className={styles.subtitle}>Найдем повторные действия, ошибки, потери токенов</p>

      <div
        className={`${styles.dropzone} ${dragActive ? styles.dropzoneActive : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
      >
        <FolderIcon className={styles.dropIcon} />
        <p className={styles.dropTitle}>Перетащите .jsonl сюда</p>
        <p className={styles.dropHint}>или выберите файл</p>
        <label className={styles.fileInput} htmlFor="log-file">
          Файл лога сессии
        </label>
        <input
          ref={inputRef}
          id="log-file"
          className={styles.fileInput}
          type="file"
          accept=".jsonl"
          onChange={onInputChange}
        />
        <Button
          variant="soft"
          className={styles.dropButton}
          onClick={() => inputRef.current?.click()}
        >
          Выбрать файл
        </Button>
      </div>

      {file && (
        <div className={styles.file}>
          <span className={styles.fileName}>{file.name}</span>
          <span className={styles.fileSize}>{formatBytes(file.size)}</span>
          <button
            type="button"
            className={styles.fileReset}
            onClick={() => {
              setFile(null);
              setFileWarning(null);
              setError(null);
            }}
          >
            Убрать
          </button>
        </div>
      )}

      {fileWarning && (
        <p className={styles.warning}>
          <AlertIcon className={styles.warningIcon} />
          <span>{fileWarning}</span>
        </p>
      )}

      <div className={styles.section}>
        <label className={styles.label} htmlFor="log-path">
          Где найти лог
        </label>
        <input
          id="log-path"
          className={`${styles.field} ${styles.path}`}
          value={LOG_PATH}
          readOnly
          onFocus={(event) => event.target.select()}
        />
        <p className={styles.fieldHint}>Claude Code хранит транскрипты сессий в этой папке.</p>
      </div>

      <label className={styles.option}>
        <input
          className={styles.checkbox}
          type="checkbox"
          checked={llmEnabled}
          onChange={(event) => setLlmEnabled(event.target.checked)}
        />
        <span>
          <span className={styles.optionTitle}>Объяснять находки моделью</span>
          <span className={styles.optionHint}>
            {llmEnabled
              ? "Фрагменты лога уйдут облачному провайдеру модели."
              : "Анализ будет только на правилах, зато ничего не уйдёт в облако."}
          </span>
        </span>
      </label>

      {error && (
        <p className={styles.error} role="alert">
          <AlertIcon className={styles.warningIcon} />
          <span>{error}</span>
        </p>
      )}

      <div className={styles.footer}>
        <Button onClick={onSubmit} disabled={!file} loading={submitting}>
          {submitting ? "Отправляем файл" : "Начать анализ"}
        </Button>
        <p className={styles.footerNote}>Поддерживается формат Claude Code JSONL, до 50 МБ</p>
      </div>
    </Layout>
  );
}
