import { useEffect, useState } from "react";
import { api, type Capture, type FaceZone, type SceneSituation, type Triage, type Trial } from "../api";
import {
  baselineWhere,
  BREAKOUT,
  CAPTURE,
  DEMO_DATA_TAG,
  MILD_SYMPTOMS,
  NEXT_STEP_LABEL,
  NOT_DIAGNOSIS,
  REACTION_RULE,
  symptomLabel,
  TRIAGE_TIER_TONE,
  ZONE_LABEL,
} from "../copy";
import { Btn, Loading, Notice, PageHead, Section, TopBar } from "../components/ui";
import { readGuide } from "../components/Guide";
import { go } from "../router";
import { useStore } from "../store";

const ZONES: FaceZone[] = ["forehead", "nose", "cheeks", "chin", "jaw"];

/**
 * The symptom screen, in two modes, because it is the same question either way: how has your skin
 * felt, and what do we do about it?
 *
 *  - With a trial id: the 10-second log that comes before the check-in scans (unchanged).
 *  - Without one ("/breakout"): Moment 2 of docs/STRATEGY.md section 4, the breakout triage.
 *
 * The breakout half follows backend/app/triage.py in order: symptoms first, then what changed
 * 2-8 weeks ago, then whether it could be purging, then where, then ONE next step. Every sentence
 * it shows comes from the engine; this screen only collects the three things the engine can't
 * know, which are what it feels like, where it is, and whether that is where she usually breaks out.
 */
export default function Checkin({ id }: { id?: string }) {
  return id ? <TrialCheckin id={id} /> : <BreakoutTriage />;
}

// ---------------------------------------------------------------- the trial check-in (unchanged)
function TrialCheckin({ id }: { id: string }) {
  const { meta, products, catalog } = useStore();
  const [t, setT] = useState<Trial | null>(null);
  const [sym, setSym] = useState<string[]>([]);
  const [others, setOthers] = useState<string[]>([]);
  const [none, setNone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [baseline, setBaseline] = useState<Capture[]>([]);

  useEffect(() => {
    api.trial(id).then(setT, (e) => setErr((e as Error).message));
    // Where and when the baseline was taken, so the check-in can be taken the same way.
    api.evidence(id).then((ev) => setBaseline(ev.captures.baseline), () => undefined);
  }, [id]);

  if (!t) return <div className="page"><TopBar back={`/trial/${id}`} />{err ? <Notice tone="stop">{err}</Notice> : <Loading />}</div>;

  const stopSet = new Set(meta?.stop_symptoms ?? []);
  const stopPicked = sym.filter((s) => stopSet.has(s));
  const toggle = (s: string) => {
    setNone(false);
    setSym((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]));
  };
  const leaveOn = products.filter((p) => p.leave_on && p.id !== t.product_id && !t.held_fixed.includes(p.id));

  const save = async (thenScan: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      await api.checkin(id, { symptoms: sym, other_new_leave_on: others });
      go(thenScan ? `/capture?mode=checkin&trial=${id}` : `/evidence/${id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  const answered = none || sym.length > 0;
  const where = baselineWhere(baseline);

  return (
    <div className="page">
      <TopBar back={`/trial/${id}`} title="Check-in" />
      <PageHead
        eyebrow={`Check-in · ${catalog[t.product_id]?.name}`}
        title="How has your skin felt?"
        lede="Symptoms come first. A reaction you can feel outranks any score."
      />

      <Section label="Stop signs">
        <div className="chips">
          {[...stopSet].map((s) => (
            <button key={s} className={`symchip symchip--stop${sym.includes(s) ? " is-on" : ""}`} onClick={() => toggle(s)} aria-pressed={sym.includes(s)}>
              {symptomLabel(s)}
            </button>
          ))}
        </div>
      </Section>
      <Section label="Also worth noting">
        <div className="chips">
          {MILD_SYMPTOMS.map((s) => (
            <button key={s} className={`symchip${sym.includes(s) ? " is-on" : ""}`} onClick={() => toggle(s)} aria-pressed={sym.includes(s)}>
              {symptomLabel(s)}
            </button>
          ))}
          <button
            className={`symchip symchip--none${none ? " is-on" : ""}`}
            onClick={() => {
              setNone(!none);
              setSym([]);
            }}
            aria-pressed={none}
          >
            Nothing, skin feels normal
          </button>
        </div>
      </Section>

      {stopPicked.length > 0 && (
        <Notice tone="stop">
          <strong>Pause {catalog[t.product_id]?.name}.</strong> You logged {stopPicked.map(symptomLabel).join(", ").toLowerCase()}.
          The verdict will be a stop, whatever the scans show. If it's severe or spreading, see a clinician.{" "}
          {REACTION_RULE}
        </Notice>
      )}

      <Section label="Anything else new since you started?">
        <p className="formhelp">Leave-on products only. Being honest here keeps the verdict honest.</p>
        <select
          className="select"
          value=""
          onChange={(e) => e.target.value && setOthers((o) => [...new Set([...o, e.target.value])])}
        >
          <option value="">Add a product…</option>
          {leaveOn.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {others.length > 0 && (
          <ul className="chips">
            {others.map((o) => (
              <li key={o}>
                <button className="symchip is-on" onClick={() => setOthers((x) => x.filter((y) => y !== o))}>
                  {catalog[o]?.name} ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {where && (
        <Section label="Before you scan">
          <p className="prose">
            {where}. {CAPTURE.sameSpot}
          </p>
        </Section>
      )}

      {err && <Notice tone="stop">{err}</Notice>}
      <div className="actions">
        <Btn onClick={() => save(true)} disabled={!answered || busy} wide>
          Save and scan
        </Btn>
        <Btn kind="ghost" onClick={() => save(false)} disabled={!answered || busy} wide>
          Save without scanning
        </Btn>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Moment 2: after a breakout
function BreakoutTriage() {
  const { meta, shelf, outcomes, health } = useStore();
  const [zones, setZones] = useState<FaceZone[]>([]);
  const [usual, setUsual] = useState<boolean | null>(null);
  const [sym, setSym] = useState<string[]>([]);
  const [none, setNone] = useState(false);
  const [res, setRes] = useState<Triage | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [situation, setSituation] = useState<SceneSituation | null>(null);

  // In demo mode the scene says what she is dealing with and since when, so the 2-8 week ranking
  // has real start dates to work from; the screen is labelled "Demo data" while it does. Outside
  // demo mode the dates come from her own outcome records, and anything with no date recorded is
  // reported as exactly that rather than guessed at.
  useEffect(() => {
    if (!health?.demo_mode && !readGuide()) return;
    api
      .demoScene("riya-breakout")
      .then((s) => {
        if (!s.situation) return;
        setSituation(s.situation);
        setZones((s.situation.zones ?? []) as FaceZone[]);
        setUsual(s.situation.usual_spots ?? null);
      })
      .catch(() => undefined);
  }, [health?.demo_mode]);

  const stopSet = new Set(meta?.stop_symptoms ?? []);
  const toggleZone = (z: FaceZone) => setZones((x) => (x.includes(z) ? x.filter((y) => y !== z) : [...x, z]));
  const toggleSym = (s: string) => {
    setNone(false);
    setSym((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]));
  };

  const using = situation?.using
    ? situation.using.map((u) => ({ product_id: u.product_id, started_on: weeksAgo(u.started_weeks_ago) }))
    : shelf.map((pid) => ({
        product_id: pid,
        started_on: outcomes.find((o) => o.product_id === pid)?.started_on ?? null,
      }));

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.triage({ symptoms: sym, zones, usual_spots: usual, using }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <TopBar back="/" />
      {health?.demo_mode && situation && <p className="tag tag--prepared">{DEMO_DATA_TAG}</p>}
      <PageHead title={BREAKOUT.title} lede={BREAKOUT.lede} />

      <Section label={BREAKOUT.symptomQ}>
        <p className="formhelp">{BREAKOUT.symptomWhy}</p>
        <div className="chips">
          {[...stopSet].map((s) => (
            <button
              key={s}
              className={`symchip symchip--stop${sym.includes(s) ? " is-on" : ""}`}
              onClick={() => toggleSym(s)}
              aria-pressed={sym.includes(s)}
            >
              {symptomLabel(s)}
            </button>
          ))}
          <button
            className={`symchip symchip--none${none ? " is-on" : ""}`}
            onClick={() => {
              setNone(!none);
              setSym([]);
            }}
            aria-pressed={none}
          >
            None of these
          </button>
        </div>
      </Section>

      <Section label={BREAKOUT.whereQ}>
        <div className="chips" role="group" aria-label={BREAKOUT.whereQ}>
          {ZONES.map((z) => (
            <button
              key={z}
              className={`symchip${zones.includes(z) ? " is-on" : ""}`}
              onClick={() => toggleZone(z)}
              aria-pressed={zones.includes(z)}
            >
              {ZONE_LABEL[z]}
            </button>
          ))}
        </div>
      </Section>

      <Section label={BREAKOUT.usualQ}>
        <p className="formhelp">{BREAKOUT.usualWhy}</p>
        <div className="segmented segmented--wrap" role="radiogroup" aria-label={BREAKOUT.usualQ}>
          {(
            [
              [true, BREAKOUT.usualYes],
              [false, BREAKOUT.usualNo],
              [null, BREAKOUT.usualUnsure],
            ] as [boolean | null, string][]
          ).map(([v, label]) => (
            <button
              key={String(v)}
              role="radio"
              aria-checked={usual === v}
              className={`segmented__opt${usual === v ? " is-on" : ""}`}
              onClick={() => setUsual(v)}
            >
              {label}
            </button>
          ))}
        </div>
      </Section>

      {err && <Notice tone="stop">{err}</Notice>}
      {!res && (
        <div className="actions">
          <Btn onClick={run} disabled={!zones.length || busy} wide>
            {busy ? "Reading your history…" : "What changed?"}
          </Btn>
          {!zones.length && <p className="small muted center">Tap at least one area first.</p>}
        </div>
      )}

      {res && <TriageResult res={res} />}

      <p className="foot small">{NOT_DIAGNOSIS}</p>
    </div>
  );
}

function TriageResult({ res }: { res: Triage }) {
  const { refresh } = useStore();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const a = res.next_action;

  // The one next step is a trial, opened through the existing trial code.
  const open = async () => {
    setBusy(true);
    setErr(null);
    try {
      const pid = a.pause_product_id ?? a.keep_product_id;
      if (!pid) return;
      const t = await api.startTrial({
        goal_concern: "acne",
        product_id: pid,
        held_fixed: a.hold_fixed ?? [],
        checkpoints_days: [a.checkpoint_days ?? 14],
      });
      await refresh();
      go(`/trial/${t.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <>
      <section className={`standout standout--${res.stop ? "stop" : "unsure"}`} aria-live="polite">
        <p className="standout__text">{res.headline}</p>
        {res.stop && <p className="small">{REACTION_RULE}</p>}
      </section>

      <Section label={BREAKOUT.zonesLabel}>
        <p className="prose">{res.zones.line}</p>
        <p className="small muted">{res.zones.source_note}</p>
      </Section>

      <Section label={BREAKOUT.purgeLabel}>
        <p className="prose">{res.purge.line}</p>
      </Section>

      <Section label={BREAKOUT.rankingLabel}>
        <ol className="ranking">
          {res.candidates.map((c) => (
            <li key={c.product_id} className={`ranking__item ranking__item--${TRIAGE_TIER_TONE[c.tier] ?? "steady"}`}>
              <span className="ranking__head">
                <strong>{c.product_name}</strong>
                {c.in_window && <span className="tag tag--unknown">{BREAKOUT.windowLabel}</span>}
                <span className="small muted">{c.leave_on ? "Stays on" : "Washed off"}</span>
              </span>
              <span className="ranking__why">{c.reason}</span>
            </li>
          ))}
        </ol>
      </Section>

      <Section label={NEXT_STEP_LABEL}>
        <p className="prose">{res.next_step}</p>
        {err && <Notice tone="stop">{err}</Notice>}
        <div className="actions">
          {a.kind === "open_trial" && (
            <Btn onClick={open} disabled={busy} wide>
              {busy ? "Opening…" : "Open the day-14 check-in"}
            </Btn>
          )}
          {a.kind === "stop_card" && (
            <Btn to="/brief" wide icon="file">
              Open my visit brief
            </Btn>
          )}
          {a.kind === "add_products" && (
            <Btn to="/shelf" wide>
              Add what I'm using
            </Btn>
          )}
        </div>
      </Section>

      <p className="foot small">
        Rule set {res.rule_version}, ingredient families {res.families_version}.
      </p>
    </>
  );
}

function weeksAgo(w: number): string {
  return new Date(Date.now() - w * 7 * 864e5).toISOString().slice(0, 10);
}
