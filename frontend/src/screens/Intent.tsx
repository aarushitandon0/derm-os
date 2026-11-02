import { useEffect, useState } from "react";
import { api, type BeginnerQuestion, type StarterPlan } from "../api";
import { BEGINNER, DEMO_DATA_TAG, inr, NOT_DIAGNOSIS } from "../copy";
import { Btn, IncompleteTag, Loading, NavBar, Notice, PageHead, RowLink, Section } from "../components/ui";
import type { IconName } from "../components/Icon";
import { KEYS, writeLocal } from "../local";
import { go } from "../router";
import { useStore } from "../store";

/**
 * Two flows on one screen, because both are "where do I start?":
 *
 *  - "/start": the returning user's chooser (unchanged).
 *  - "/start-here": Start here, for someone with no history at all. Four questions, then their
 *    skin type, their top measured concerns in plain words, and a 3-step starter that has been
 *    run through the same cart check as any other purchase.
 *
 * Skin type is labelled with where it came from. Until a verification scan has confirmed what SD
 * skin_type returns, that label reads "from your answers", and the screen says so out loud.
 */
export default function Intent({ beginner }: { beginner?: boolean }) {
  return beginner ? <StartHere /> : <Chooser />;
}

// ---------------------------------------------------------------- Start here
function StartHere() {
  const { health, refresh } = useStore();
  const [questions, setQuestions] = useState<BeginnerQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<StarterPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.beginnerQuestions().then((q) => setQuestions(q.questions), (e) => setErr((e as Error).message));
  }, []);

  const done = !!questions && questions.every((q) => answers[q.id]);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      writeLocal(KEYS.onboarded, true);
      setPlan(await api.beginnerPlan(answers));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (err && !questions)
    return (
      <div className="page">
        <NavBar back="/" />
        <Notice tone="stop">{err}</Notice>
      </div>
    );
  if (!questions)
    return (
      <div className="page">
        <NavBar back="/" />
        <Loading />
      </div>
    );

  if (plan) return <StarterView plan={plan} onRefresh={refresh} demo={!!health?.demo_mode} />;

  return (
    <div className="page">
      <NavBar back="/" />
      <PageHead title={BEGINNER.title} lede={BEGINNER.lede} />
      {questions.map((q) => (
        <Section key={q.id} label={q.text}>
          <p className="formhelp">{q.why}</p>
          <div className="choices" role="radiogroup" aria-label={q.text}>
            {q.choices.map((c) => (
              <RowLink
                key={c.value}
                radio
                title={c.label}
                selected={answers[q.id] === c.value}
                onClick={() => setAnswers((a) => ({ ...a, [q.id]: c.value }))}
                trailing={<span className="radio" aria-hidden />}
              />
            ))}
          </div>
        </Section>
      ))}
      {err && <Notice tone="stop">{err}</Notice>}
      <div className="actions">
        <Btn onClick={run} disabled={!done || busy} wide>
          {busy ? "Reading your answers…" : "See where to start"}
        </Btn>
      </div>
      <p className="foot small">{NOT_DIAGNOSIS}</p>
    </div>
  );
}

function StarterView({
  plan,
  onRefresh,
  demo,
}: {
  plan: StarterPlan;
  onRefresh: () => Promise<void>;
  demo: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const first = plan.steps.find((s) => s.role === "cleanser") ?? plan.steps[0];

  // "Start one at a time" is the whole point, so the first trial is opened on one product.
  const start = async () => {
    if (!first) return;
    setBusy(true);
    setErr(null);
    try {
      await api.setShelf(plan.steps.map((s) => s.product.id));
      const t = await api.startTrial({
        goal_concern: plan.concerns[0]?.concern ?? first.product.aimed_at?.[0] ?? "pore",
        product_id: first.product.id,
        held_fixed: plan.steps.filter((s) => s.product.id !== first.product.id).map((s) => s.product.id),
      });
      await onRefresh();
      go(`/trial/${t.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <NavBar back="/" />
      {demo && <p className="tag tag--prepared">{DEMO_DATA_TAG}</p>}
      <PageHead eyebrow={BEGINNER.title} title={BEGINNER.typeLabel} lede={plan.skin_type.line} />

      <section className="standout standout--steady">
        <p className="standout__kicker">
          {plan.skin_type.value ?? "Not clear yet"} <span className="tag tag--unknown">{plan.skin_type.label}</span>
        </p>
        {plan.skin_type.source === "answers" && <p className="small">{BEGINNER.noScanYet}</p>}
        {Object.keys(plan.skin_type.zones).length > 0 && (
          <p className="small">
            By zone: {Object.entries(plan.skin_type.zones).map(([z, t]) => `${z} ${t}`).join(", ")}.
          </p>
        )}
      </section>

      <Section label={BEGINNER.concernsLabel}>
        {plan.concerns.length === 0 ? (
          <p className="muted">
            Nothing measured yet. Your first scan reads your top concerns and sets the range every later
            scan is judged against.
          </p>
        ) : (
          <ul className="srclines">
            {plan.concerns.map((c) => (
              <li key={c.concern}>{c.sentence}</li>
            ))}
          </ul>
        )}
      </Section>

      <Section label={BEGINNER.starterLabel}>
        <ol className="starter">
          {plan.steps.map((s) => (
            <li key={s.product.id} className="starter__step">
              <span className="starter__role">{s.role}</span>
              <span className="starter__name">
                {s.product.brand} {s.product.name} · {inr(s.product.price_inr)}
              </span>
              <span className={`starter__verdict starter__verdict--${s.check.rung}`}>{s.check.verdict_line}</span>
              {!s.product.inci_complete && <IncompleteTag />}
              <a className="textbtn" href={`#/store/${s.product.id}`}>
                See the full check
              </a>
            </li>
          ))}
        </ol>
      </Section>

      <Section label={BEGINNER.oneAtATimeLabel}>
        <p className="prose">{plan.one_at_a_time}</p>
      </Section>

      <Section label="Your next step">
        <p className="prose">{plan.next_step}</p>
        {err && <Notice tone="stop">{err}</Notice>}
        <div className="actions">
          <Btn onClick={start} disabled={busy || !first} wide>
            {busy ? "Opening…" : "Start my first trial"}
          </Btn>
        </div>
      </Section>

      <p className="foot small">
        {NOT_DIAGNOSIS} Rule set {plan.rule_version}. All products shown are fictional.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- the returning user's chooser
type Choice = "review" | "start" | "compare" | "brief";

function Chooser() {
  const { activeTrial, trials, shelf } = useStore();
  const [pick, setPick] = useState<Choice | null>(null);
  const latest = activeTrial ?? trials[trials.length - 1] ?? null;

  const options: { id: Choice; icon: IconName; title: string; sub: string }[] = [
    { id: "review", icon: "progress", title: "Track progress", sub: "See real changes over time" },
    { id: "start", icon: "search", title: "Understand my skin", sub: "Start with your routine and history" },
    { id: "compare", icon: "routine", title: "Plan a routine", sub: "Make one change at a time" },
    { id: "brief", icon: "file", title: "Prepare for a dermatologist visit", sub: "Get a clear, concise brief" },
  ];

  const target = (c: Choice) => {
    if (c === "review") return "/progress";
    if (c === "start") return shelf.length ? "/history" : "/shelf";
    if (c === "compare") return "/compare";
    return latest ? `/brief/${latest.id}` : "/brief";
  };

  const go2 = () => {
    if (!pick) return;
    writeLocal(KEYS.onboarded, true);
    go(target(pick));
  };

  return (
    <div className="page page--flow">
      <NavBar back="/" center={<span className="stepbar" role="progressbar" aria-label="Setup" aria-valuemin={1} aria-valuemax={2} aria-valuenow={1}><span /></span>} />
      <PageHead title="What brings you here?" lede="We'll tailor your experience." />
      <div className="choices" role="radiogroup" aria-label="What brings you here?">
        {options.map((o) => (
          <RowLink
            key={o.id}
            radio
            icon={o.icon}
            title={o.title}
            sub={o.sub}
            selected={pick === o.id}
            onClick={() => setPick(o.id)}
            trailing={<span className="radio" aria-hidden />}
          />
        ))}
      </div>
      <div className="flow__foot">
        <Btn onClick={go2} disabled={!pick} wide>
          Continue
        </Btn>
        <button
          type="button"
          className="textbtn textbtn--center"
          onClick={() => {
            writeLocal(KEYS.onboarded, true);
            go("/");
          }}
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}
