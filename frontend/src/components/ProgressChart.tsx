import type { Evidence, Range } from "../api";
import { concernLabel, fmtDate } from "../copy";

type Point = { x: number; y: number; score: number; kind: "baseline" | "compared" | "not_compared"; at: string };

const W = 340;
const H = 236;
const M = { l: 30, r: 12, t: 40, b: 44 };
const PW = W - M.l - M.r;
const PH = H - M.t - M.b;

/** A y-range around the data (raw scores live on 0-100), at least 20 points tall, with round ticks. */
function yDomain(vals: number[]): { lo: number; hi: number; ticks: number[] } {
  if (!vals.length) return { lo: 0, hi: 100, ticks: [0, 25, 50, 75, 100] };
  let lo = Math.floor((Math.min(...vals) - 6) / 5) * 5;
  let hi = Math.ceil((Math.max(...vals) + 6) / 5) * 5;
  if (hi - lo < 20) {
    const pad = (20 - (hi - lo)) / 2;
    lo -= Math.ceil(pad / 5) * 5;
    hi += Math.ceil(pad / 5) * 5;
  }
  lo = Math.max(0, lo);
  hi = Math.min(100, hi);
  const step = [5, 10, 20, 25].find((s) => (hi - lo) / s <= 5) ?? 25;
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  return { lo, hi, ticks };
}

/**
 * Raw scores over time for one concern. Only the baseline and check-ins that pass the
 * comparability gate are joined into the line; the rest are hollow and labelled "not compared".
 * The shaded band is the baseline range (the personal noise floor), widened by MIN_BAND.
 */
export function ProgressChart({
  ev,
  concern,
  band,
  productName,
}: {
  ev: Evidence;
  concern: string;
  band: number;
  productName: string;
}) {
  const caps = ev.series.filter((c) => typeof c.raw_scores?.[concern] === "number");
  const range: Range | undefined = ev.baseline_ranges[concern];
  const nBase = caps.filter((c) => c.phase === "baseline").length;
  const dom = yDomain([
    ...caps.map((c) => c.raw_scores[concern]),
    ...(range ? [range.lo - band, range.hi + band] : []),
  ]);
  const yOf = (v: number) => M.t + PH - ((Math.max(dom.lo, Math.min(dom.hi, v)) - dom.lo) / (dom.hi - dom.lo)) * PH;

  // Ordinal x positions, with a half-step gap where the product starts.
  const slots = caps.map((c, i) => i + (c.phase !== "baseline" && nBase > 0 ? 0.6 : 0));
  const last = slots.length ? slots[slots.length - 1] : 0;
  const span = Math.max(last, 1);
  const xOf = (s: number) => (caps.length === 1 ? M.l + PW / 2 : M.l + 8 + (s / span) * (PW - 16));

  const pts: Point[] = caps.map((c, i) => ({
    x: xOf(slots[i]),
    y: yOf(c.raw_scores[concern]),
    score: c.raw_scores[concern],
    at: c.taken_at,
    kind: c.phase === "baseline" ? "baseline" : c.comparable ? "compared" : "not_compared",
  }));
  const joined = pts.filter((p) => p.kind !== "not_compared");
  const line = joined.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  const startX =
    nBase > 0
      ? nBase < caps.length
        ? (pts[nBase - 1].x + pts[nBase].x) / 2
        : Math.min(pts[nBase - 1].x + 18, M.l + PW)
      : null;

  // x labels: the baseline group, then one label per check-in date.
  const groups: { label: string; sub: string; x: number }[] = [];
  const base = pts.filter((p) => p.kind === "baseline");
  if (base.length) groups.push({ label: "Baseline", sub: fmtDate(base[0].at), x: (base[0].x + base[base.length - 1].x) / 2 });
  const byDate = new Map<string, Point[]>();
  pts.filter((p) => p.kind !== "baseline").forEach((p) => {
    const k = new Date(p.at).toDateString();
    byDate.set(k, [...(byDate.get(k) ?? []), p]);
  });
  byDate.forEach((ps) => groups.push({ label: "Check-in", sub: fmtDate(ps[0].at), x: (ps[0].x + ps[ps.length - 1].x) / 2 }));

  const name = productName.length > 24 ? productName.slice(0, 23) + "…" : productName;
  const summary = range
    ? `${concernLabel(concern)} raw score, axis ${dom.lo} to ${dom.hi}: noise floor ${range.lo.toFixed(1)} to ${range.hi.toFixed(1)}. ${joined.length} scans compared, ${
        pts.length - joined.length
      } not compared.`
    : `${concernLabel(concern)}: no baseline yet.`;

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} className="chart__svg">
        {dom.ticks.map((v) => (
          <text key={v} x={M.l - 8} y={yOf(v) + 4} className="chart__tick" textAnchor="end">
            {v}
          </text>
        ))}
        <line x1={M.l} x2={W - M.r} y1={yOf(dom.lo)} y2={yOf(dom.lo)} className="chart__axis" />
        {range && (
          <rect
            x={M.l}
            width={PW}
            y={yOf(range.hi + band)}
            height={Math.max(yOf(range.lo - band) - yOf(range.hi + band), 3)}
            className="chart__band"
            rx="3"
          />
        )}
        {startX !== null && (
          <g>
            <line x1={startX} x2={startX} y1={M.t - 8} y2={yOf(dom.lo)} className="chart__start" />
            <text x={startX + 6} y={M.t - 26} className="chart__startlabel">
              Started
            </text>
            <text x={startX + 6} y={M.t - 12} className="chart__startlabel chart__startlabel--name">
              {name}
            </text>
          </g>
        )}
        {joined.length > 1 && <path d={line} className="chart__line" />}
        {pts.map((p, i) =>
          p.kind === "not_compared" ? (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r="4.5" className="chart__pt chart__pt--hollow" />
              <text x={p.x} y={p.y + (i % 2 ? 20 : -11)} className="chart__note" textAnchor="middle">
                not compared
              </text>
            </g>
          ) : (
            <circle key={i} cx={p.x} cy={p.y} r="3.8" className="chart__pt" />
          )
        )}
        {groups.map((g, i) => (
          <g key={i}>
            <text x={g.x} y={H - 24} className="chart__xlabel" textAnchor="middle">
              {g.label}
            </text>
            <text x={g.x} y={H - 9} className="chart__xlabel chart__xlabel--sub" textAnchor="middle">
              {g.sub}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="chart__legend">
        <span className="chart__axisnote">Raw score, axis {dom.lo}–{dom.hi} of 100</span>
        <span className="chart__key">
          <svg width="22" height="10" aria-hidden>
            <line x1="1" x2="21" y1="5" y2="5" className="chart__line" />
            <circle cx="11" cy="5" r="3.2" className="chart__pt" />
          </svg>
          Your score
        </span>
        <span className="chart__key">
          <span className="chart__swatch" aria-hidden />
          Your noise floor
        </span>
        {pts.some((p) => p.kind === "not_compared") && (
          <span className="chart__key">
            <svg width="12" height="12" aria-hidden>
              <circle cx="6" cy="6" r="4" className="chart__pt chart__pt--hollow" />
            </svg>
            Not compared
          </span>
        )}
      </figcaption>
      <table className="sr-only">
        <caption>{concernLabel(concern)} raw scores</caption>
        <thead>
          <tr>
            <th>Date</th>
            <th>Score</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {pts.map((p, i) => (
            <tr key={i}>
              <td>{fmtDate(p.at)}</td>
              <td>{p.score.toFixed(1)}</td>
              <td>{p.kind === "baseline" ? "Baseline" : p.kind === "compared" ? "Compared" : "Not compared"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
