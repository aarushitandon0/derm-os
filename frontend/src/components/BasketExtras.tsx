import { useEffect, useState } from "react";
import {
  api,
  type ChipIn,
  type ChipOut,
  type ChipReaction,
  type ChipsState,
  type LookFor as LookForData,
  type PasteJob,
  type PasteResult,
  type StartPlan,
} from "../api";
import { RECORD } from "../copy";
import { buildDayIcs, downloadIcs } from "../ics";
import { Btn, Notice } from "./ui";

// Basket question 2, the start plan, "what to look for" and the paste check. Every sentence the
// user reads about their history comes from the engines (app/chips.py, startplan.py, lookfor.py,
// pastecheck.py); this file only lays them out.

const toIn = (c: ChipOut): ChipIn => ({
  chip: c.chip,
  reaction: c.reaction,
  product_name: c.product_name,
  confirmed_allergy: c.confirmed_allergy,
  usual_spots_settled: c.usual_spots_settled,
  purge_choice: c.purge_choice,
});

/** The chips grid: tap an ingredient, then say what happened. Saved as you go. */
export function ChipsPicker() {
  const [state, setState] = useState<ChipsState | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [extra, setExtra] = useState<{ id: string; label: string }[]>([]);
  const [free, setFree] = useState("");
  const [freeLine, setFreeLine] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.chips().then(setState, (e) => setErr((e as Error).message));
  }, []);

  if (err) return <Notice tone="stop">{err}</Notice>;
  if (!state) return null;

  const save = async (next: ChipIn[]) => {
    try {
      setState(await api.setChips(next));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const current = state.chips.map(toIn);
  const upsert = (id: string, patch: Partial<ChipIn>) => {
    const have = current.find((c) => c.chip === id);
    const row: ChipIn = { ...(have ?? { chip: id, reaction: "not_sure" }), ...patch };
    // A new reaction resets the purge question: it is asked again, never carried over.
    if (patch.reaction && have && patch.reaction !== have.reaction) {
      row.usual_spots_settled = null;
      row.purge_choice = null;
    }
    save(have ? current.map((c) => (c.chip === id ? row : c)) : [...current, row]);
  };
  const remove = (id: string) => save(current.filter((c) => c.chip !== id));

  const tiles = [
    ...state.catalogue.map((c) => ({ id: c.id, label: c.label })),
    ...extra.filter((x) => !state.catalogue.some((c) => c.id === x.id)),
    ...state.chips
      .filter((c) => !state.catalogue.some((x) => x.id === c.chip) && !extra.some((x) => x.id === c.chip))
      .map((c) => ({ id: c.chip, label: c.label })),
  ];

  const match = async () => {
    if (!free.trim()) return;
    const r = await api.matchChip(free.trim());
    setFreeLine(r.line);
    if (r.match) {
      setExtra((x) => [...x, { id: r.match!.id, label: r.match!.label }]);
      setOpen(r.match.id);
      setFree("");
    }
  };

  const reactions = Object.entries(state.reactions) as [ChipReaction, string][];
  const sel = open ? state.chips.find((c) => c.chip === open) : undefined;

  return (
    <div className="chipq">
      <ul className="chips" aria-label="Ingredients">
        {tiles.map((t) => {
          const got = state.chips.find((c) => c.chip === t.id);
          return (
            <li key={t.id}>
              <button
                type="button"
                className={`symchip chipq__tile${got ? " is-on" : ""}${open === t.id ? " is-open" : ""}`}
                aria-expanded={open === t.id}
                onClick={() => setOpen(open === t.id ? null : t.id)}
              >
                {t.label}
                {got && <span className="chipq__react"> · {got.reaction_label}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      {open && (
        <div className="chipq__panel">
          <p className="chipq__ask">{tiles.find((t) => t.id === open)?.label}: what happened?</p>
          <div className="chips" role="radiogroup" aria-label="What happened">
            {reactions.map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={sel?.reaction === value}
                className={`symchip symchip--sm${sel?.reaction === value ? " is-on" : ""}`}
                onClick={() => upsert(open, { reaction: value })}
              >
                {label}
              </button>
            ))}
          </div>
          {sel && (
            <>
              <p className="small chipq__line">{sel.line}</p>
              <label className="field field--compact">
                <span>Product name (optional)</span>
                <input
                  defaultValue={sel.product_name}
                  maxLength={80}
                  onBlur={(e) => e.target.value !== sel.product_name && upsert(open, { product_name: e.target.value })}
                />
              </label>
              {sel.reaction === "itched" && (
                <label className="chipq__check">
                  <input
                    type="checkbox"
                    checked={sel.confirmed_allergy}
                    onChange={(e) => upsert(open, { confirmed_allergy: e.target.checked })}
                  />{" "}
                  {RECORD.confirmed_allergy.label}
                </label>
              )}
              {sel.purge_question && <PurgeQuestion chip={sel} onPick={(p) => upsert(open, p)} />}
              <button type="button" className="textbtn small" onClick={() => (remove(open), setOpen(null))}>
                Remove {sel.word}
              </button>
            </>
          )}
        </div>
      )}

      <div className="chipq__free">
        <label className="field field--compact">
          <span>Something else? Type an ingredient</span>
          <input value={free} maxLength={60} onChange={(e) => setFree(e.target.value)} placeholder="e.g. glycolic acid" />
        </label>
        <Btn kind="ghost" onClick={match} disabled={!free.trim()}>
          Find it
        </Btn>
      </div>
      {freeLine && <p className="small muted">{freeLine}</p>}
    </div>
  );
}

/** Asked once for a purge-capable ingredient. A yes only OFFERS purging: the user picks. */
function PurgeQuestion({ chip, onPick }: { chip: ChipOut; onPick: (p: Partial<ChipIn>) => void }) {
  const answers: { v: "yes" | "no" | "not_sure"; l: string }[] = [
    { v: "yes", l: "Yes" },
    { v: "no", l: "No" },
    { v: "not_sure", l: "Not sure" },
  ];
  return (
    <div className="purgeq">
      <p className="purgeq__q">{chip.purge_question}</p>
      <div className="chips" role="radiogroup" aria-label={chip.purge_question ?? ""}>
        {answers.map((a) => (
          <button
            key={a.v}
            type="button"
            role="radio"
            aria-checked={chip.usual_spots_settled === a.v}
            className={`symchip symchip--sm${chip.usual_spots_settled === a.v ? " is-on" : ""}`}
            onClick={() => onPick({ usual_spots_settled: a.v, purge_choice: null })}
          >
            {a.l}
          </button>
        ))}
      </div>
      {chip.purge_offer && (
        <>
          <p className="purgeq__offer">{chip.purge_offer}</p>
          <div className="chips" role="radiogroup" aria-label="Your choice">
            <button
              type="button"
              role="radio"
              aria-checked={chip.purge_choice === "purging"}
              className={`symchip symchip--sm${chip.purge_choice === "purging" ? " is-on" : ""}`}
              onClick={() => onPick({ purge_choice: "purging" })}
            >
              Record as possible purging
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={chip.purge_choice === "breakout"}
              className={`symchip symchip--sm${chip.purge_choice === "breakout" ? " is-on" : ""}`}
              onClick={() => onPick({ purge_choice: "breakout" })}
            >
              Keep it as a breakout
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** The dated start plan, one calendar file per step. */
export function StartPlanCard({ plan, demo }: { plan: StartPlan; demo: boolean }) {
  const add = (s: StartPlan["steps"][number]) =>
    downloadIcs(
      `dermos-start-${s.order}.ics`,
      buildDayIcs(
        `start-${s.product_id}-${s.start_on}`,
        s.start_on,
        `derm//os: start ${s.name}`,
        `${s.line} ${plan.if_reacts}`
      )
    );
  return (
    <div className="plan">
      {demo && <p className="small muted">Dates count from today.</p>}
      <p className="prose">{plan.patch_line}</p>
      <p className="prose">{plan.spacing_line}</p>
      {plan.steps.length > 0 ? (
        <ol className="plan__steps">
          {plan.steps.map((s) => (
            <li key={s.product_id} className="plan__step">
              <span className="plan__group">{s.group}</span>
              <span className="plan__line">{s.line}</span>
              <Btn kind="quiet" onClick={() => add(s)} icon="bell">
                Add to calendar
              </Btn>
            </li>
          ))}
        </ol>
      ) : (
        <p className="prose">Nothing new to start: everything in this basket is already yours.</p>
      )}
      {plan.keep.length > 0 && (
        <ul className="srclines">
          {plan.keep.map((k) => (
            <li key={k.product_id}>{k.line}</li>
          ))}
        </ul>
      )}
      <div className="plan__stop">
        <p className="prose">{plan.if_reacts}</p>
        <div className="plan__links">
          <Btn kind="ghost" to="/breakout" icon="alert">
            Open the stop card
          </Btn>
          <Btn kind="quiet" to="/brief" icon="file">
            Dermatologist brief
          </Btn>
        </div>
      </div>
      {plan.sources.length > 0 && (
        <p className="small muted plan__src">
          Sources:{" "}
          {plan.sources.map((s, i) => (
            <span key={s.id}>
              {i > 0 && " · "}
              <a href={s.url} target="_blank" rel="noreferrer">
                {s.text}
              </a>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

/** "What to look for" on a basket card. Works in any shop; never names a brand. */
export function LookFor({ data }: { data: LookForData }) {
  if (!data.lines.length) return null;
  return (
    <div className="lookfor">
      <p className="lookfor__title">What to look for, in any shop</p>
      <ul className="lookfor__lines">
        {data.lines.map((l) => (
          <li key={l} className={l.startsWith("Avoid:") ? "lookfor__avoid" : undefined}>
            {l}
          </li>
        ))}
      </ul>
    </div>
  );
}

const JOBS: { v: PasteJob; l: string }[] = [
  { v: "cleanser", l: "Cleanser" },
  { v: "moisturiser", l: "Moisturiser" },
  { v: "sunscreen", l: "Sunscreen" },
  { v: "serum", l: "Serum" },
];

/** Paste any product's ingredient list. Nothing is stored; only a nickname you type is shown. */
export function PasteCheck() {
  const [text, setText] = useState("");
  const [job, setJob] = useState<PasteJob>("moisturiser");
  const [nick, setNick] = useState("");
  const [res, setRes] = useState<PasteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.pasteCheck(text, job, nick.trim() || undefined));
    } catch (e) {
      setErr((e as Error).message);
      setRes(null);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="paste">
      <label className="field">
        <span>Paste the ingredient list from the pack or the product page</span>
        <textarea
          className="paste__text"
          rows={5}
          maxLength={4000}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Water, Glycerin, Niacinamide, …"
        />
      </label>
      <p className="formhelp">Its job</p>
      <div className="chips" role="radiogroup" aria-label="Its job">
        {JOBS.map((j) => (
          <button
            key={j.v}
            type="button"
            role="radio"
            aria-checked={job === j.v}
            className={`symchip symchip--sm${job === j.v ? " is-on" : ""}`}
            onClick={() => setJob(j.v)}
          >
            {j.l}
          </button>
        ))}
      </div>
      <label className="field paste__nick">
        <span>Nickname (optional)</span>
        <input value={nick} maxLength={40} onChange={(e) => setNick(e.target.value)} placeholder="e.g. the gel from the pharmacy" />
      </label>
      <Btn onClick={run} disabled={busy || !text.trim()} wide>
        {busy ? "Checking…" : "Check it"}
      </Btn>
      <p className="small muted">Nothing you paste is saved, and brand names are never shown.</p>
      {err && <Notice tone="stop">{err}</Notice>}
      {res && (
        <section className={`pasteres pasteres--${res.rung}`} aria-live="polite">
          <p className="pasteres__name">{res.name}</p>
          <p className="pasteres__verdict">{res.verdict_line}</p>
          {res.sources.map((s) => (
            <div key={s.key} className="pasteres__src">
              <p className="pasteres__label">{s.label}</p>
              <ul className="srclines">
                {s.lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          ))}
          {res.parse_notes.length > 0 && <p className="small muted">{res.parse_notes.join(" ")}</p>}
          <p className="prose nextstep">{res.next_step}</p>
        </section>
      )}
    </div>
  );
}
