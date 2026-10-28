import type { Finding } from "../api";
import { concernLabel } from "../copy";

// Baseline range vs follow-up range on one shared scale.
// Overlap = no detectable change. The caption never claims more than the
// verdict: when the photos aren't comparable, it says the bars aren't compared.
export function RangeBar({
  finding,
  baseScores,
  followScores,
  band = 0,
  compared = true,
}: {
  finding: Finding;
  baseScores: number[];
  followScores: number[];
  band?: number;
  compared?: boolean;
}) {
  const b = finding.baseline;
  const f = finding.followup;
  const all = [...baseScores, ...followScores, b?.lo, b?.hi, f?.lo, f?.hi].filter(
    (x): x is number => typeof x === "number"
  );
  if (!all.length) return null;
  const lo = Math.floor(Math.min(...all) - band - 3);
  const hi = Math.ceil(Math.max(...all) + band + 3);
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const span = (a: number, z: number) => ({ left: pos(a), width: `${Math.max(((z - a) / (hi - lo)) * 100, 0.8)}%` });

  const overlap = b && f ? [Math.max(b.lo - band, f.lo - band), Math.min(b.hi + band, f.hi + band)] : null;
  const hasOverlap = overlap && overlap[0] <= overlap[1];

  let caption: string;
  if (!b || !f) caption = !b ? "Waiting for baseline scans." : "Waiting for check-in scans.";
  else if (!compared) caption = "Not compared: the photos were taken under different conditions.";
  else if (hasOverlap) caption = "The ranges overlap: no detectable change.";
  else
    caption = `No overlap: moved ${Math.abs(finding.delta_mid ?? 0).toFixed(1)} points beyond your own range, toward ${
      finding.direction === "better" ? "healthier" : "less healthy"
    }-looking.`;

  return (
    <figure className="rangebar">
      <figcaption className="rangebar__title">
        <span>{concernLabel(finding.concern)}</span>
        <span className="mono muted">raw score</span>
      </figcaption>
      <div className="rangebar__plot" aria-hidden>
        {hasOverlap && compared && (
          <div className="rangebar__overlaywrap">
            <div className="rangebar__overlap" style={span(overlap![0], overlap![1])} />
          </div>
        )}
        <Row label="Baseline" n={b?.n} range={b} scores={baseScores} span={span} pos={pos} kind="base" band={band} />
        <Row label="Check-in" n={f?.n} range={f} scores={followScores} span={span} pos={pos} kind="follow" band={band} />
        <div className="rangebar__axis mono">
          <span>{lo}</span>
          <span>{hi}</span>
        </div>
      </div>
      <p className={`rangebar__caption${compared ? "" : " rangebar__caption--muted"}`}>{caption}</p>
      <p className="sr-only">
        Baseline {b ? `${b.lo} to ${b.hi}` : "missing"}; check-in {f ? `${f.lo} to ${f.hi}` : "missing"}. {caption}
      </p>
    </figure>
  );
}

function Row({
  label,
  n,
  range,
  scores,
  span,
  pos,
  kind,
  band,
}: {
  label: string;
  n?: number;
  range: { lo: number; hi: number } | null | undefined;
  scores: number[];
  span: (a: number, z: number) => { left: string; width: string };
  pos: (v: number) => string;
  kind: "base" | "follow";
  band: number;
}) {
  return (
    <div className={`rangebar__row rangebar__row--${kind}`}>
      <span className="rangebar__label">
        {label}
        {n ? <span className="mono muted"> · {n}</span> : null}
      </span>
      <div className="rangebar__track">
        {range && band > 0 && <div className="rangebar__pad" style={span(range.lo - band, range.hi + band)} />}
        {range && <div className="rangebar__span" style={span(range.lo, range.hi)} />}
        {scores.map((s, i) => (
          <span key={i} className="rangebar__dot" style={{ left: pos(s) }} title={s.toFixed(1)} />
        ))}
        {range && (
          <span className="rangebar__nums mono" style={{ left: pos((range.lo + range.hi) / 2) }}>
            {range.lo.toFixed(1)}–{range.hi.toFixed(1)}
          </span>
        )}
      </div>
    </div>
  );
}
