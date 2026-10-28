import { GUIDE_STEPS, useGuideNav } from "../components/Guide";
import { Btn, NavBar, Notice, PageHead } from "../components/ui";
import { NOT_DIAGNOSIS } from "../copy";
import { KEYS, writeLocal } from "../local";
import { useStore } from "../store";

// The guided demo's start page: what you'll see, in order, before the first step loads.
export default function Demo({ step }: { step: number }) {
  const { health } = useStore();
  const { open, busy, error } = useGuideNav();
  const unavailable = health ? health.server_demo_mode === false : false;

  const start = () => {
    writeLocal(KEYS.onboarded, true);
    void open(Number.isFinite(step) && step > 0 ? Math.min(step, GUIDE_STEPS.length) - 1 : 0);
  };

  return (
    <div className="page page--flow">
      <NavBar back="/welcome" />
      <PageHead
        title="The 90-second demo"
        lede="Riya is deciding whether a new moisturiser is worth it. Then Meera, whose trial shows a change."
      />
      <p className="tag tag--prepared demo__tag">Prepared demo data</p>
      <ol className="demo__steps">
        {GUIDE_STEPS.map((s, i) => (
          <li key={i} className="demo__step">
            <span className="demo__num" aria-hidden>
              {i + 1}
            </span>
            <span className="demo__body">
              <span className="demo__title">{s.title}</span>
              <span className="demo__look">{s.look}</span>
            </span>
          </li>
        ))}
      </ol>
      {unavailable && <Notice tone="warn">This server is set up for live scans, so the prepared demo is off here.</Notice>}
      {error && <Notice tone="stop">{error}</Notice>}
      <div className="flow__foot">
        <Btn onClick={start} wide icon="arrow" disabled={busy || unavailable}>
          {busy ? "Loading…" : "Start the demo"}
        </Btn>
        <p className="small muted center">
          Scores are prepared from recorded data; every verdict is worked out by the same engine as a real trial. {NOT_DIAGNOSIS}
        </p>
      </div>
    </div>
  );
}
