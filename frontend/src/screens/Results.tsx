import { useCallback, useEffect, useState } from "react";
import { api, assetUrl, type Capture, type Evidence, type Finding, type Range } from "../api";
import { concernLabel, fmtDate, fmtLong, fmtTime, MASKS_DEMO, VERDICT } from "../copy";
import { RangeBar } from "../components/RangeBar";
import { ReactionList, StopCard } from "../components/Reactions";
import { Btn, Loading, NavBar, Notice, PageHead, PreparedTag, Section, Segmented, TabPanel } from "../components/ui";
import { ComparabilityBadge } from "../components/Verdict";
import { TrialNotes } from "../components/TrialNotes";
import { useStore } from "../store";

type TabId = "overview" | "concerns" | "notes";

export default function Results({ id }: { id: string }) {
  const { meta, refresh } = useStore();
  const [ev, setEv] = useState<Evidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("overview");

  const load = useCallback(() => {
    api.evidence(id).then(
      (e) => {
        setEv(e);
        setErr(null);
      },
      (e) => setErr((e as Error).message)
    );
  }, [id]);
  useEffect(load, [load]);

  const changed = () => {
    load();
    void refresh();
  };

  if (err)
    return (
      <div className="page">
        <NavBar back="/" />
        <Notice tone="stop">{err}</Notice>
      </div>
    );
  if (!ev)
    return (
      <div className="page">
        <NavBar back="/" />
        <Loading label="Reading your scans" />
      </div>
    );

  const { report, captures, trial } = ev;
  const all = [...captures.baseline, ...captures.followup];
  const prepared = ev.series.some((c) => c.source === "replay");
  const latest = ev.series[ev.series.length - 1];
  const goal = report.findings.find((f) => f.concern === trial.goal_concern) ?? report.findings[0];
  const v = VERDICT[report.verdict];
  const scores = (cs: Capture[], k: string) => cs.map((c) => c.raw_scores[k]).filter((x): x is number => typeof x === "number");

  return (
    <div className="page">
      <NavBar back={`/trial/${id}`} />
      <PageHead
        title="Your results"
        lede={latest ? `${fmtLong(latest.taken_at)} · ${fmtTime(latest.taken_at)}` : `Trial started ${fmtLong(trial.started_at)}`}
      />
      <Segmented
        idBase="results"
        label="Results sections"
        value={tab}
        onChange={setTab}
        options={[
          { value: "overview", label: "Overview" },
          { value: "concerns", label: "Concerns" },
          { value: "notes", label: "Notes" },
        ]}
      />

      {tab === "overview" && (
        <TabPanel idBase="results" value="overview">
          <StopCard trialId={id} productName={ev.product.name} reactions={ev.reactions} onChanged={changed} />
          <MaskHero concern={trial.goal_concern} base={captures.baseline} follow={captures.followup} />
          <section className={`standout standout--${v.tone}`} aria-live="polite">
            <div className="standout__head">
              <h2 className="h2">What stands out</h2>
              {prepared && <PreparedTag />}
            </div>
            <p className="standout__text">{report.message}</p>
            <p className="standout__next">{v.next}</p>
          </section>

          <Section
            label="Concerns"
            aside={
              <button type="button" className="textbtn" onClick={() => setTab("concerns")}>
                See all
              </button>
            }
          >
            {goal ? <ConcernRow f={goal} /> : <p className="muted">Ranges appear after the baseline and a check-in.</p>}
          </Section>

          <div className="actions">
            <Btn to={`/checkin/${id}`} wide>
              New check-in
            </Btn>
            <Btn kind="ghost" to={`/progress?trial=${id}`} wide>
              See progress
            </Btn>
          </div>
        </TabPanel>
      )}

      {tab === "concerns" && (
        <TabPanel idBase="results" value="concerns">
          <Section label="Your range vs this check-in">
            {report.findings.length === 0 ? (
              <p className="muted">Bars appear once there are baseline and check-in scans.</p>
            ) : (
              report.findings.map((f) => (
                <RangeBar
                  key={f.concern}
                  finding={f}
                  baseScores={scores(captures.baseline, f.concern)}
                  followScores={scores(captures.followup, f.concern)}
                  band={meta?.min_band ?? 0}
                  compared={report.comparability?.comparable !== false}
                />
              ))
            )}
            <p className="small muted">
              YouCam raw scores (higher reads as healthier-looking). The app's display score is adjusted upward by design, so it
              is never used to judge change.
            </p>
          </Section>
          <Section label="Conditions">
            <ComparabilityBadge c={report.comparability} retakeTo={`/capture?mode=checkin&trial=${id}`} />
            <Conditions base={captures.baseline} follow={captures.followup} />
          </Section>
          <OtherConcerns ev={ev} />
          <Section label="What YouCam marked">
            <Masks concern={trial.goal_concern} base={captures.baseline} follow={captures.followup} prepared={all.some((c) => c.source === "replay")} />
          </Section>
        </TabPanel>
      )}

      {tab === "notes" && (
        <TabPanel idBase="results" value="notes">
          <Section label="Reactions">
            <ReactionList trialId={id} reactions={ev.reactions} onChanged={changed} />
          </Section>
          <Section label="Your notes">
            <TrialNotes trialId={id} />
          </Section>
          <Section label="Timeline">
            <ol className="timeline">
              {ev.timeline.map((e, i) => (
                <li key={i} className={`timeline__item timeline__item--${e.kind}`}>
                  <span className="timeline__date">{fmtDate(e.at)}</span>
                  <span>{e.text}</span>
                </li>
              ))}
            </ol>
          </Section>
          <div className="actions">
            <Btn kind="ghost" to={`/brief/${id}`} wide icon="file">
              Visit brief
            </Btn>
          </div>
          <p className="foot small">
            Rule set {report.rule_version}. The strongest thing derm//os says is “changed during this trial”, never “caused by”.
          </p>
        </TabPanel>
      )}
    </div>
  );
}

/** Goal concern: latest check-in range (clay) against the baseline range (grey) on a 0-100 track. */
function ConcernRow({ f }: { f: Finding }) {
  // Both ranges on one zoomed scale so a 2-point range is visible; the numbers stay exact.
  const vals = [f.baseline?.lo, f.baseline?.hi, f.followup?.lo, f.followup?.hi].filter((x): x is number => typeof x === "number");
  const lo = vals.length ? Math.max(0, Math.floor(Math.min(...vals) - 4)) : 0;
  const hi = vals.length ? Math.min(100, Math.ceil(Math.max(...vals) + 4)) : 100;
  const span = Math.max(hi - lo, 1);
  const pos = (r: Range) => ({ left: `${((r.lo - lo) / span) * 100}%`, width: `${Math.max(((r.hi - r.lo) / span) * 100, 2)}%` });
  return (
    <div className="concern">
      <div className="concern__line">
        <span className="concern__name">
          <span className="concern__dot concern__dot--latest" aria-hidden />
          {concernLabel(f.concern)}
        </span>
        <span className="concern__track" aria-hidden>
          {f.followup && <span className="concern__bar concern__bar--latest" style={pos(f.followup)} />}
        </span>
        <span className="concern__nums">{f.followup ? `${f.followup.lo.toFixed(1)}–${f.followup.hi.toFixed(1)}` : "–"}</span>
      </div>
      <div className="concern__line">
        <span className="concern__name concern__name--sub">
          <span className="concern__dot" aria-hidden />
          Your range
        </span>
        <span className="concern__track" aria-hidden>
          {f.baseline && <span className="concern__bar concern__bar--base" style={pos(f.baseline)} />}
        </span>
        <span className="concern__nums">{f.baseline ? `${f.baseline.lo.toFixed(1)}–${f.baseline.hi.toFixed(1)}` : "–"}</span>
      </div>
      <p className="concern__scale" aria-hidden>
        Scale {lo}–{hi} of 100 · raw score
      </p>
      <p className="sr-only">
        {concernLabel(f.concern)}: baseline {f.baseline ? `${f.baseline.lo} to ${f.baseline.hi}` : "missing"}, latest check-in{" "}
        {f.followup ? `${f.followup.lo} to ${f.followup.hi}` : "missing"}, raw score out of 100.
      </p>
    </div>
  );
}

/** Other scanned concerns: ranges only. They are not judged in this trial. */
function OtherConcerns({ ev }: { ev: Evidence }) {
  const goal = ev.trial.goal_concern;
  const keys = Object.keys(ev.baseline_ranges).filter((k) => k !== goal).sort();
  if (!keys.length) return null;
  const follow = ev.captures.followup;
  const fr = (k: string) => {
    const v = follow.map((c) => c.raw_scores[k]).filter((x): x is number => typeof x === "number");
    return v.length ? `${Math.min(...v).toFixed(1)}–${Math.max(...v).toFixed(1)}` : "–";
  };
  return (
    <Section label="Also scanned">
      <p className="small muted">Shown for reference only. This trial judges {concernLabel(goal).toLowerCase()}.</p>
      <table className="conds">
        <thead>
          <tr>
            <th />
            <th>Baseline</th>
            <th>Latest check-in</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <th>{concernLabel(k)}</th>
              <td className="num">
                {ev.baseline_ranges[k].lo.toFixed(1)}–{ev.baseline_ranges[k].hi.toFixed(1)}
              </td>
              <td className="num">{fr(k)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

function avg(xs: (number | null | undefined)[]) {
  const v = xs.filter((x): x is number => typeof x === "number");
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

function Conditions({ base, follow }: { base: Capture[]; follow: Capture[] }) {
  if (!base.length || !follow.length) return null;
  const rows: [string, (c: Capture) => number | null | undefined, (n: number) => string][] = [
    ["Brightness", (c) => c.fingerprint.luminance, (n) => n.toFixed(2)],
    ["Light warmth (R/B)", (c) => c.fingerprint.red_blue_ratio, (n) => n.toFixed(2)],
    ["Face width", (c) => c.fingerprint.face_ratio, (n) => `${Math.round(n * 100)}%`],
    ["Head turn", (c) => c.fingerprint.yaw, (n) => `${n.toFixed(0)}°`],
  ];
  return (
    <table className="conds">
      <thead>
        <tr>
          <th />
          <th>Baseline</th>
          <th>Check-in</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, get, fmt]) => {
          const a = avg(base.map(get));
          const b = avg(follow.map(get));
          return (
            <tr key={label}>
              <th>{label}</th>
              <td className="num">{a === null ? "–" : fmt(a)}</td>
              <td className="num">{b === null ? "–" : fmt(b)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function maskOf(cs: Capture[], concern: string, fromEnd = false) {
  const list = fromEnd ? [...cs].reverse() : cs;
  return assetUrl(list.find((c) => c.masks?.[concern]?.length)?.masks[concern][0]);
}

/** The hero image is YouCam's own marked-area mask, never a stock face. Hidden when there is none. */
function MaskHero({ concern, base, follow }: { concern: string; base: Capture[]; follow: Capture[] }) {
  const src = maskOf(follow, concern, true) ?? maskOf(base, concern);
  if (!src) return null;
  return (
    <figure className="maskhero">
      <img src={src} alt={`Areas YouCam marked for ${concernLabel(concern).toLowerCase()}`} />
    </figure>
  );
}

function Masks({ concern, base, follow, prepared }: { concern: string; base: Capture[]; follow: Capture[]; prepared: boolean }) {
  const b = maskOf(base, concern);
  const f = maskOf(follow, concern, true);
  if (!b && !f && !prepared) return <p className="muted small">No mask images saved for these scans.</p>;
  return (
    <>
    <div className="masks">
      {(
        [
          ["Baseline", b],
          ["Check-in", f],
        ] as const
      ).map(([label, src]) => (
        <figure key={label} className="masks__fig">
          {src ? (
            <img src={src} alt={`${label} ${concernLabel(concern)} mask from YouCam`} loading="lazy" />
          ) : (
            <div className="masks__empty">No mask</div>
          )}
          <figcaption>{label}</figcaption>
        </figure>
      ))}
    </div>
    {prepared && (!b || !f) && <p className="muted small">{MASKS_DEMO}</p>}
    </>
  );
}
