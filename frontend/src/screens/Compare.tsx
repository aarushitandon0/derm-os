import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, CONCERNS, type Column, type CompareResult, type Product } from "../api";
import { CHECK, concernLabel, inr, ROLE_LABEL } from "../copy";
import { Btn, Loading, Notice, PageHead, TopBar } from "../components/ui";
import { go } from "../router";
import { useStore } from "../store";

type Mode = "add" | "replace" | null;
const OPTS = ["Option A", "Option B"] as const;

export default function Compare({ initial }: { initial?: { a?: string | null; b?: string | null } }) {
  const { products, catalog, shelf, refresh } = useStore();
  const [pick, setPick] = useState<Record<string, string>>({
    "Option A": initial?.a ?? "",
    "Option B": initial?.b ?? "",
  });
  const [modes, setModes] = useState<Record<string, Mode>>({ "Option A": null, "Option B": null });
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const chosen = OPTS.filter((o) => pick[o]);
  useEffect(() => {
    if (!chosen.length) {
      setResult(null);
      return;
    }
    let live = true;
    setLoading(true);
    api
      .compare(chosen.map((o) => ({ name: o, items: [{ product_id: pick[o], mode: modes[o] }] })))
      .then((r) => live && (setResult(r), setErr(null)))
      .catch((e) => live && setErr((e as Error).message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [pick["Option A"], pick["Option B"], modes["Option A"], modes["Option B"], shelf.join()]);

  const answer = (qid: string, choice: string) => {
    const name = qid.split(":")[1];
    setModes((m) => ({ ...m, [name]: choice as Mode }));
  };

  const cols = result?.columns ?? [];
  const q = result?.next_question ?? null;

  return (
    <div className="page page--wide">
      <TopBar title="Compare" />
      <PageHead
        title="Change nothing is always an option."
        lede="Each option is applied to your current shelf and checked against your history, line by line."
      />

      {!shelf.length && (
        <Notice tone="warn">
          Your shelf is empty, so every option is compared to an empty routine. <a href="#/shelf">Add your products</a>.
        </Notice>
      )}

      <div className="optpickers">
        {OPTS.map((o) => (
          <label key={o} className="field">
            <span>{o}</span>
            <select
              value={pick[o]}
              onChange={(e) => {
                setPick((p) => ({ ...p, [o]: e.target.value }));
                setModes((m) => ({ ...m, [o]: null }));
              }}
            >
              <option value="">None</option>
              {products
                .filter((p) => !shelf.includes(p.id))
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {inr(p.price_inr)}
                  </option>
                ))}
            </select>
          </label>
        ))}
      </div>

      {q && (
        <div className="question" role="group" aria-label="One question that changes the table">
          <p className="eyebrow">One question changes this table</p>
          <p className="question__text">{q.text}</p>
          <p className="question__why">{q.why}</p>
          <div className="question__btns">
            {q.choices.map((c) => (
              <Btn key={c} kind={c === "replace" ? "primary" : "ghost"} onClick={() => answer(q.id, c)}>
                {c === "replace" ? "Replacing it" : "Adding alongside"}
              </Btn>
            ))}
          </div>
          <p className="question__note">Until you answer, the table assumes “adding”.</p>
        </div>
      )}

      {err && <Notice tone="stop">{err}</Notice>}
      {loading && !result && <Loading label="Comparing" />}
      {!chosen.length && <p className="muted center">Pick one or two options to compare with changing nothing.</p>}

      {cols.length > 0 && (
        <div className={`ctable ctable--${cols.length}${loading ? " is-loading" : ""}`}>
          <div className="ctable__row ctable__row--head">
            {cols.map((c) => (
              <div key={c.name} className={`ctable__cell ctable__colhead${c.blocked ? " is-blocked" : ""}`}>
                <span className="eyebrow">{c.name}</span>
                <span className="ctable__pname">
                  {c.name === "Change nothing" ? "Your shelf as is" : catalog[pick[c.name]]?.name}
                </span>
                {c.name !== "Change nothing" && (
                  <ModeToggle
                    value={modes[c.name]}
                    canReplace={!!sameRole(catalog[pick[c.name]], shelf, catalog)}
                    onChange={(m) => setModes((x) => ({ ...x, [c.name]: m }))}
                  />
                )}
              </div>
            ))}
          </div>

          <Row label="Exclusion check" cols={cols} render={(c) => <ExclusionCell c={c} />} />
          <Row label="What changes" cols={cols} render={(c) => <ChangeCell c={c} catalog={catalog} />} />
          <Row label="New spend" cols={cols} render={(c) => <span className="num">{inr(c.new_spend_inr)}</span>} />
          <Row
            label="New leave-on products"
            cols={cols}
            render={(c) => (
              <span>
                <span className="num">{c.new_leave_on}</span>
                {c.new_leave_on > 1 && <span className="cell-note">More than one: a trial couldn't tell which did what.</span>}
              </span>
            )}
          />
          <Row
            label="Doubled-up steps"
            cols={cols}
            render={(c) =>
              c.duplicate_roles.length ? (
                <span>{c.duplicate_roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")}</span>
              ) : (
                <span className="muted">None</span>
              )
            }
          />
          <Row
            label="Routine"
            cols={cols}
            render={(c) => (
              <ol className="steps">
                {c.steps.map((s) => (
                  <li key={s} className={c.added.includes(s) || c.replaced.some((r) => r.in === s) ? "is-new" : ""}>
                    {catalog[s]?.name}
                  </li>
                ))}
              </ol>
            )}
          />
          <div className="ctable__row ctable__row--foot">
            {cols.map((c) => (
              <div key={c.name} className="ctable__cell">
                {c.name === "Change nothing" ? (
                  <span className="muted small">Costs nothing and changes nothing. A fair choice.</span>
                ) : (
                  <StartTrial col={c} productId={pick[c.name]} onStarted={refresh} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function sameRole(p: Product | undefined, shelf: string[], cat: Record<string, Product>) {
  return p && shelf.find((s) => cat[s]?.role === p.role);
}

function Row({ label, cols, render }: { label: string; cols: Column[]; render: (c: Column) => ReactNode }) {
  return (
    <>
      <div className="ctable__label">{label}</div>
      <div className="ctable__row">
        {cols.map((c) => (
          <div key={c.name} className="ctable__cell">
            {render(c)}
          </div>
        ))}
      </div>
    </>
  );
}

function ModeToggle({ value, canReplace, onChange }: { value: Mode; canReplace: boolean; onChange: (m: Mode) => void }) {
  if (!canReplace) return <span className="small muted">Adds a new step</span>;
  return (
    <span className="minitoggle">
      {(["add", "replace"] as const).map((m) => (
        <button key={m} className={(value ?? "add") === m ? "is-on" : ""} onClick={() => onChange(m)}>
          {m === "add" ? "Adds" : "Replaces"}
        </button>
      ))}
      {value === null && <span className="minitoggle__q">unanswered</span>}
    </span>
  );
}

function ExclusionCell({ c }: { c: Column }) {
  if (!c.checks.length) return <span className="muted">Nothing new to check</span>;
  return (
    <div className="excl">
      {c.checks.map((k) => (
        <div key={k.product_id} className={`excl__item excl--${k.status}`}>
          <span className={`status status--${k.status}`}>{CHECK[k.status].label}</span>
          {k.status === "blocked" ? (
            k.matches.map((m, i) =>
              m.label_line ? (
                <span key={i} className="excl__line">
                  Label line: <q className="labelline">{m.label_line}</q>
                  <span className="excl__why">{k.reasons[i]}</span>
                </span>
              ) : (
                <span key={i} className="excl__why">
                  {k.reasons[i]}
                </span>
              )
            )
          ) : (
            <span className="excl__why">{k.reasons[0]}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function ChangeCell({ c, catalog }: { c: Column; catalog: Record<string, Product> }) {
  if (!c.added.length && !c.replaced.length) return <span className="muted">Nothing</span>;
  return (
    <ul className="changes">
      {c.replaced.map((r) => (
        <li key={r.in}>
          <span className="changes__verb">Replaces</span> {catalog[r.out]?.name}
        </li>
      ))}
      {c.added.map((a) => (
        <li key={a}>
          <span className="changes__verb">Adds</span> {catalog[a]?.name}
        </li>
      ))}
      <li className="muted">Keeps {c.kept.length}</li>
    </ul>
  );
}

function StartTrial({ col, productId, onStarted }: { col: Column; productId: string; onStarted: () => Promise<void> }) {
  const [concern, setConcern] = useState("redness");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const reason = useMemo(() => {
    if (col.blocked) return "Blocked by your history, so it can't be trialled.";
    if (col.new_leave_on > 1) return "More than one new leave-on product: a trial couldn't tell which did what.";
    if (col.open_questions.length) return "Answer the question above first.";
    return null;
  }, [col]);

  if (reason) return <span className="small muted">{reason}</span>;

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.setShelf(col.steps);
      const t = await api.startTrial({
        goal_concern: concern,
        product_id: productId,
        held_fixed: col.steps.filter((s) => s !== productId),
      });
      await onStarted();
      go(`/capture?mode=baseline&trial=${t.id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Couldn't start the trial.");
      setBusy(false);
    }
  };

  return (
    <div className="starttrial">
      {col.unknowns.length > 0 && (
        <span className="cell-note">Its full label isn't available, so your exclusions couldn't be checked.</span>
      )}
      <label className="field field--compact">
        <span>Watch</span>
        <select value={concern} onChange={(e) => setConcern(e.target.value)}>
          {CONCERNS.map((c) => (
            <option key={c} value={c}>
              {concernLabel(c)}
            </option>
          ))}
        </select>
      </label>
      <Btn onClick={start} disabled={busy} wide>
        {busy ? "Starting…" : "Try this"}
      </Btn>
      <span className="small muted">Your shelf becomes this routine.</span>
      {err && <span className="cell-note cell-note--stop">{err}</span>}
    </div>
  );
}
