import type { Comparability, Report } from "../api";
import { CONDITION, CONDITION_ROWS, VERDICT } from "../copy";

const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

// One glance: a kicker word, the engine's own sentence, the next step.
// The sentence comes from the backend (evidence.VERDICT_TEXT), never rewritten here.
export function VerdictHero({ report }: { report: Report }) {
  const v = VERDICT[report.verdict];
  return (
    <section className={`verdict verdict--${v.tone}`} aria-live="polite">
      <p className="verdict__kicker">
        <span className="verdict__glyph" aria-hidden />
        {v.kicker}
      </p>
      <p className="verdict__sentence">{report.message}</p>
      <p className="verdict__next">{v.next}</p>
      <RebuyLine text={report.rebuy} />
    </section>
  );
}

/** The shopping decision, as the backend mapped it from the verdict. Never computed here. */
export function RebuyLine({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <p className="rebuy">
      <span className="rebuy__label">Rebuy?</span>
      <span>{text}</span>
    </p>
  );
}

export function ComparabilityBadge({ c, retakeTo }: { c: Comparability | null; retakeTo?: string }) {
  if (!c) return <div className="compbadge compbadge--none">Comparability: waiting for both scan sets</div>;
  if (c.comparable) {
    // Name only what was actually compared; fields with no data on both sides are listed apart.
    const checked = c.checked ? CONDITION_ROWS.filter((f) => c.checked!.includes(f)) : null;
    const skipped = (c.not_compared ?? []).map((x) => x.field);
    const missing = checked ? CONDITION_ROWS.filter((f) => !checked.includes(f) && !skipped.includes(f)) : [];
    const names = (fs: typeof CONDITION_ROWS) => fs.map((f) => CONDITION[f].label.toLowerCase());
    return (
      <div className="compbadge compbadge--ok">
        <strong>Comparable</strong>
        <span>
          {checked
            ? `${list(names(checked)).replace(/^./, (x) => x.toUpperCase())} match your baseline within tolerance.`
            : "Matches your baseline within tolerance."}
        </span>
        {missing.length > 0 && <span className="small muted">Not recorded, so not compared: {list(names(missing))}.</span>}
        {(c.not_compared ?? []).map((x) => (
          <span key={x.field} className="small muted">
            {CONDITION[x.field].label}: not compared. {x.reason}
          </span>
        ))}
      </div>
    );
  }
  return (
    <div className="compbadge compbadge--bad">
      <strong>Not comparable</strong>
      <ul className="compbadge__list">
        {c.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {c.fixes.length > 0 && (
        <>
          <p className="compbadge__fixhead">For the retake</p>
          <ul className="compbadge__list compbadge__list--fix">
            {c.fixes.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </>
      )}
      {retakeTo && (
        <a className="btn btn--ghost" href={`#${retakeTo}`}>
          Retake check-in
        </a>
      )}
    </div>
  );
}
