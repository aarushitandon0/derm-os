import { useEffect, useState } from "react";
import { api, type Capture, type Trial } from "../api";
import { baselineWhere, CAPTURE, MILD_SYMPTOMS, REACTION_RULE, symptomLabel } from "../copy";
import { Btn, Loading, Notice, PageHead, Section, TopBar } from "../components/ui";
import { go } from "../router";
import { useStore } from "../store";

// The 10-second symptom log that comes before the check-in scans.
export default function Checkin({ id }: { id: string }) {
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
