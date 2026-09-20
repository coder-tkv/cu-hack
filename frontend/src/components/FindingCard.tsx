import { useState } from "react";
import type { Finding, Recommendation } from "../api/types";
import {
  assessmentLabel,
  explanationSourceNote,
  factLabel,
  factValue,
  stepLabel,
} from "../utils/labels";
import { EvidenceViewer } from "./EvidenceViewer";
import { ExternalLinkIcon, QuoteIcon } from "./icons";
import styles from "./FindingCard.module.css";

const PILLS = 8;

/**
 * Одна находка = строка из трёх карточек макета:
 * «Место в коде» (строки исходного файла), «Проблема», «Рекомендации».
 * Доказательства и полный текст рекомендации раскрываются под строкой.
 */
export function FindingCard({
  finding,
  recommendations,
  sessionId,
}: {
  finding: Finding;
  recommendations: Recommendation[];
  sessionId: string;
}) {
  const [pillLimit, setPillLimit] = useState(PILLS);
  // null = доказательства скрыты; массив = какие шаги показываем
  const [evidence, setEvidence] = useState<string[] | null>(null);
  const [recOpen, setRecOpen] = useState(false);
  const [factsOpen, setFactsOpen] = useState(false);

  const steps = finding.evidence_step_ids;
  const visiblePills = steps.slice(0, pillLimit);
  const sourceNote = explanationSourceNote(finding.explanation_source);
  const facts = Object.entries(finding.facts).filter(([key]) => key !== "fact_text");
  const factText = typeof finding.facts["fact_text"] === "string" ? finding.facts["fact_text"] : null;

  const toggleEvidence = (ids: string[]) => {
    setEvidence((current) =>
      current !== null && current.length === ids.length && current.every((id, i) => id === ids[i])
        ? null
        : ids,
    );
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.row}>
        <section className={styles.panel}>
          <h3 className={styles.panelTitle}>Место в коде</h3>
          {steps.length === 0 && <p className={styles.muted}>Шаги лога не привязаны</p>}
          <div className={styles.pills}>
            {visiblePills.map((stepId) => (
              <button
                key={stepId}
                type="button"
                className={`${styles.pill} ${evidence?.length === 1 && evidence[0] === stepId ? styles.pillActive : ""}`}
                onClick={() => toggleEvidence([stepId])}
              >
                {stepLabel(stepId)}
              </button>
            ))}
          </div>
          {pillLimit < steps.length && (
            <button
              type="button"
              className={styles.link}
              onClick={() => setPillLimit((value) => value + PILLS)}
            >
              Показать ещё ({steps.length - pillLimit})
            </button>
          )}
          {steps.length > 0 && (
            <button type="button" className={styles.link} onClick={() => toggleEvidence(steps)}>
              {evidence !== null && evidence.length === steps.length
                ? "Скрыть доказательства"
                : "Показать доказательства"}
            </button>
          )}
        </section>

        <section className={styles.panel}>
          <h3 className={styles.panelTitle}>Проблема</h3>
          <p className={styles.findingTitle}>{finding.title}</p>

          <div className={styles.badges}>
            <span className={`${styles.badge} ${styles[`severity_${finding.severity}`]}`}>
              {finding.severity === "high"
                ? "Высокий"
                : finding.severity === "medium"
                  ? "Средний"
                  : "Низкий"}
            </span>
            <span className={styles.badgeSoft}>{assessmentLabel(finding.assessment)}</span>
            {sourceNote && <span className={styles.badgeMuted}>{sourceNote}</span>}
          </div>

          {/* Основной текст: объяснение, а если его нет — факт, посчитанный кодом. */}
          {finding.explanation ? (
            <p className={styles.text}>{finding.explanation}</p>
          ) : (
            factText && <p className={styles.text}>{factText}</p>
          )}

          {finding.likely_cause && (
            <div className={styles.cause}>
              <span className={styles.causeLabel}>Возможная причина</span>
              <p className={styles.text}>{finding.likely_cause}</p>
            </div>
          )}

          {facts.length > 0 && (
            <>
              <button
                type="button"
                className={styles.link}
                aria-expanded={factsOpen}
                onClick={() => setFactsOpen((value) => !value)}
              >
                {factsOpen ? "Скрыть факты" : `Факты (${facts.length})`}
              </button>
              {factsOpen && (
                <dl className={styles.facts}>
                  {finding.explanation && factText && (
                    <p className={styles.text}>{factText}</p>
                  )}
                  {facts.map(([key, value]) => (
                    <div key={key} className={styles.factRow}>
                      <dt className={styles.factKey}>{factLabel(key)}</dt>
                      <dd className={styles.factValue}>{factValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          )}

          {finding.limitations.length > 0 && (
            <div className={styles.limitations}>
              <span className={styles.causeLabel}>Ограничения</span>
              <ul className={styles.list}>
                {finding.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <h3 className={styles.panelTitle}>Рекомендации</h3>
            {recommendations.length > 0 && (
              <button
                type="button"
                className={styles.iconButton}
                aria-label={recOpen ? "Свернуть рекомендации" : "Развернуть рекомендации"}
                aria-expanded={recOpen}
                onClick={() => setRecOpen((value) => !value)}
              >
                <ExternalLinkIcon />
              </button>
            )}
          </div>

          {recommendations.length === 0 && (
            <p className={styles.muted}>Для этой находки рекомендаций нет</p>
          )}

          {recommendations.map((rec) => (
            <div key={rec.recommendation_id} className={styles.quote}>
              <QuoteIcon className={styles.quoteOpen} />
              <p className={`${styles.quoteText} ${recOpen ? "" : styles.quoteClamp}`}>
                {rec.action}
              </p>

              {recOpen && (
                <div className={styles.recDetails}>
                  <p className={styles.recLine}>
                    <span className={styles.recLabel}>Почему</span>
                    {rec.rationale}
                  </p>
                  {rec.verification && (
                    <p className={styles.recLine}>
                      <span className={styles.recLabel}>Как проверить</span>
                      {rec.verification}
                    </p>
                  )}
                  {rec.rule_text && (
                    <p className={styles.recLine}>
                      <span className={styles.recLabel}>Правило для проекта</span>
                      {rec.rule_text}
                    </p>
                  )}
                  {rec.source === "rule_based" && (
                    <p className={styles.recSource}>шаблонная рекомендация</p>
                  )}
                  {rec.source === "not_explained" && (
                    <p className={styles.recSource}>модель не участвовала</p>
                  )}
                </div>
              )}
              <QuoteIcon className={styles.quoteClose} />
            </div>
          ))}
        </section>
      </div>

      {evidence !== null && (
        <div className={styles.evidence}>
          <EvidenceViewer sessionId={sessionId} stepIds={evidence} />
        </div>
      )}
    </div>
  );
}
