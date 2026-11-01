import { useState } from "react";
import { api, ApiError } from "../api";
import { readLocal, writeLocal } from "../local";
import { go } from "../router";
import { useStore } from "../store";

// The 90-second guided demo: Riya's hero flow from docs/DESIGN.md, then a second person whose
// check-ins leave her own range. Each step loads a prepared scene on the server (app/scenes.py);
// the verdicts on these screens come from the real engine, like any other trial.
export interface GuideStep {
  scene: string;
  title: string;
  look: string; // what to look at on this screen
  to: (trialId: string | null) => string;
}

export const GUIDE_STEPS: GuideStep[] = [
  {
    scene: "riya-store",
    title: "What her skin has already told her",
    look: "Two products that itched, one that broke her out, two that suited her. The engine reads one suspect out of that: alcohol denat., in 2 of 2 that itched and 0 of 2 that suited her.",
    to: () => "/history",
  },
  {
    scene: "riya-store",
    title: "Moment 1: the sale",
    look: "Three products, three different answers. Tap “Check against my skin” on each.",
    to: () => "/store",
  },
  {
    scene: "riya-store",
    title: "Repeats a pattern",
    look: "The vitamin C on sale lists her suspect by name, with the counts from her own records. One next step, and “change nothing” is still offered.",
    to: () => "/store/sr-08",
  },
  {
    scene: "riya-store",
    title: "Unknown, never a pass",
    look: "The bundle's ingredient list is incomplete, so it reads “Ingredient list incomplete → unknown”. An ingredient that isn't printed stays unknown, and unknown is never a pass.",
    to: () => "/store/mo-07",
  },
  {
    scene: "riya-store",
    title: "No conflicts, and aimed at her pores",
    look: "Nothing of hers matched. The skin source says what it is aimed at, against her measured scores, in the words “aimed at”.",
    to: () => "/store/sr-09",
  },
  {
    scene: "riya-breakout",
    title: "Moment 2: she breaks out",
    look: "Closed comedones on the cheeks, not her usual spots. The sunscreen started 4 weeks ago is the lead; the snail mucin she has used 12 weeks ranks lowest, with the reason shown. Not a purge: no turnover ingredient.",
    to: () => "/breakout",
  },
  {
    scene: "riya-history",
    title: "Her history, the three record types",
    look: "Her reaction to a fragranced moisturiser is filed against that product only. Avoiding fragrance is her separate choice.",
    to: () => "/history",
  },
  {
    scene: "riya-history",
    title: "Two sale options",
    look: "Option A is blocked, with the exact label line. Option B's label is incomplete, so it shows unknown, never a pass.",
    to: () => "/compare?a=sr-02&b=mo-04",
  },
  {
    scene: "riya-trial",
    title: "One change, a 3-scan baseline",
    look: "She tries a third option that passes. Everything else is held fixed, and 3 scans set her own range.",
    to: (t) => `/trial/${t}`,
  },
  {
    scene: "riya-lamp",
    title: "Same face, warm lamp",
    look: "The check-in was taken under a warm lamp. The gate says the photos aren't comparable and shows how to retake.",
    to: (t) => `/results/${t}`,
  },
  {
    scene: "riya-day14",
    title: "Day 14, window light again",
    look: "Comparable photos. Read the verdict and the rebuy line under it.",
    to: (t) => `/results/${t}`,
  },
  {
    scene: "riya-stop",
    title: "She logs itching",
    look: "A reported reaction outranks any score: the stop card, and a rebuy line that says don't.",
    to: (t) => `/results/${t}`,
  },
  {
    scene: "riya-stop",
    title: "Visit brief",
    look: "One page to take to a clinician: timeline, the full label, symptoms and what the scans could and couldn't say.",
    to: (t) => `/brief/${t}`,
  },
  {
    scene: "meera",
    title: "Another trial: Meera",
    look: "Her comparable check-ins leave her own range. The strongest wording is still “during this trial”.",
    to: (t) => `/results/${t}`,
  },
  {
    scene: "meera-pore",
    title: "Moment 3: a result that does say something",
    look: "Her pores moved 6 raw points past her own range, on comparable photos. Read the grey line a typical app would lead with, then the derm//os verdict in bold under it.",
    to: (t) => `/results/${t}`,
  },
  {
    scene: "meera-pore",
    title: "The loop closes",
    look: "The verdict is written into that product's record, so the next purchase check knows it. A result that can't tell either way is written as “not sure”, never as suiting you.",
    to: () => "/history",
  },
  {
    scene: "beginner",
    title: "Start here, from nothing",
    look: "No shelf, no history, no scan. Four questions, then a skin type labelled “from your answers” and a 3-step starter put through the same check as any purchase.",
    to: () => "/start-here",
  },
];

const KEY = "guide";
interface GuideState {
  step: number; // index into GUIDE_STEPS
  scene: string;
  trialId: string | null;
}

export const readGuide = () => readLocal<GuideState | null>(KEY, null);
const writeGuide = (g: GuideState | null) => writeLocal(KEY, g);

/** Load step `i`'s scene (if it isn't loaded already) and open its screen. */
export function useGuideNav() {
  const { refresh } = useStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = async (i: number) => {
    const step = GUIDE_STEPS[i];
    if (!step) return;
    setBusy(true);
    setError(null);
    try {
      const cur = readGuide();
      let trialId = cur?.scene === step.scene ? cur.trialId : null;
      if (cur?.scene !== step.scene) trialId = (await api.demoScene(step.scene)).trial_id;
      writeGuide({ step: i, scene: step.scene, trialId });
      await refresh();
      go(step.to(trialId));
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? "The guided demo needs the server's demo mode, and this server is set up for live scans."
          : e instanceof ApiError
          ? e.message
          : "Couldn't load this step. Try again."
      );
    } finally {
      setBusy(false);
    }
  };
  const exit = () => {
    writeGuide(null);
    go("/");
  };
  return { open, exit, busy, error };
}

/** Pinned under the demo label on every screen while the guided demo runs. */
export function GuideBar({ path }: { path: string[] }) {
  const g = readGuide();
  const { open, exit, busy, error } = useGuideNav();
  if (!g || path[0] === "demo" || path[0] === "welcome") return null;
  const step = GUIDE_STEPS[g.step];
  if (!step) return null;
  const last = g.step === GUIDE_STEPS.length - 1;
  return (
    <aside className="guidebar no-print" aria-label="Guided demo">
      <div className="guidebar__top">
        <span className="tag tag--prepared">Prepared demo data</span>
        <span className="guidebar__count">
          Step {g.step + 1} of {GUIDE_STEPS.length}
        </span>
      </div>
      <ol className="guidebar__dots" aria-hidden>
        {GUIDE_STEPS.map((_s, i) => (
          <li key={i} className={i < g.step ? "is-done" : i === g.step ? "is-now" : ""} />
        ))}
      </ol>
      <p className="guidebar__title">{step.title}</p>
      <p className="guidebar__look">{step.look}</p>
      {error && (
        <p className="guidebar__err" role="alert">
          {error}
        </p>
      )}
      <div className="guidebar__btns">
        <button type="button" className="btn btn--quiet" onClick={() => (g.step ? open(g.step - 1) : go("/demo"))} disabled={busy}>
          Back
        </button>
        <button type="button" className="btn btn--primary" onClick={() => (last ? exit() : open(g.step + 1))} disabled={busy}>
          {busy ? "Loading…" : last ? "Finish" : "Next"}
        </button>
        <button type="button" className="textbtn guidebar__exit" onClick={exit}>
          Exit demo
        </button>
      </div>
    </aside>
  );
}
