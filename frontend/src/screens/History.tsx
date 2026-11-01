import { useState } from "react";
import {
  api,
  type FaceZone,
  type IntakeResult,
  type OutcomeValue,
  type PatternReport,
  type Product,
  type Proposal,
  type RecordType,
} from "../api";
import {
  GENERAL_LABEL,
  OUTCOME,
  OUTCOME_HELP,
  OUTCOMES_LEDE,
  PATTERN_KIND,
  PERSONAL_LABEL,
  RECORD,
  SUITED_RULE,
  TIER,
  ZONE_LABEL,
} from "../copy";
import { Btn, IncompleteTag, Notice, PageHead, Section, TopBar } from "../components/ui";
import { useStore } from "../store";

const TYPES: RecordType[] = ["suspected_reaction", "avoid", "confirmed_allergy"];
const SUGGEST = ["fragrance", "linalool", "limonene", "essential oils", "alcohol denat", "salicylic acid", "retinol", "methylisothiazolinone"];

export default function History() {
  const { history, products, catalog, refresh, health } = useStore();
  const [type, setType] = useState<RecordType>("suspected_reaction");
  const [productId, setProductId] = useState("");
  const [ingredient, setIngredient] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [suggest, setSuggest] = useState<{ product: string; line: string } | null>(null);
  const target = RECORD[type].target;

  const add = async () => {
    setErr(null);
    setBusy(true);
    try {
      await api.addRecord({
        type,
        product_id: target === "product" ? productId : null,
        ingredient: target === "ingredient" ? ingredient.trim() : null,
        note,
      });
      const p = target === "product" ? catalog[productId] : undefined;
      const line = p?.inci.find((x) => /parfum|fragrance|perfume/i.test(x));
      const alreadyAvoids = history.some((r) => r.type !== "suspected_reaction" && /fragrance|parfum/i.test(r.ingredient ?? ""));
      setSuggest(p && line && !alreadyAvoids ? { product: p.name, line } : null);
      setProductId("");
      setIngredient("");
      setNote("");
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await api.removeRecord(id);
    await refresh();
  };

  const canAdd = target === "product" ? !!productId : ingredient.trim().length > 1;

  return (
    <div className="page">
      <TopBar title="History" />
      <PageHead
        title="Three kinds of record, kept apart."
        lede="A product that bothered you, an ingredient you avoid by choice and a clinician-confirmed allergy have different effects."
      />

      {/* What happened, product by product. This is the memory the three moments read, and it is
          kept apart from the three blocking record types below it on purpose. */}
      <Outcomes />
      <Patterns />

      <ul className="kinds">
        {TYPES.map((t) => (
          <li key={t} className="kind">
            <span className={`chip chip--${t}`}>{RECORD[t].short}</span>
            <span>
              <strong>{RECORD[t].label}.</strong> {RECORD[t].rule}
            </span>
          </li>
        ))}
      </ul>

      <Section label={`Your records (${history.length})`}>
        {history.length === 0 ? (
          <p className="muted">Nothing recorded yet. That means nothing is blocked; it doesn't mean everything suits you.</p>
        ) : (
          <ul className="records">
            {history.map((r) => (
              <li key={r.id} className="record">
                <span className={`chip chip--${r.type}`}>{RECORD[r.type].short}</span>
                <span className="record__what">
                  {r.type === "suspected_reaction" ? catalog[r.product_id ?? ""]?.name ?? r.product_id : r.ingredient}
                  {r.note && <span className="record__note">{r.note}</span>}
                </span>
                <button className="record__x" onClick={() => remove(r.id)} aria-label="Remove record">
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {suggest && (
        <div className="suggest">
          <p>
            Saved as a reaction to <strong>{suggest.product}</strong> only. Its label lists “{suggest.line}”. Do you also
            want to avoid fragrance by choice? That's a separate record: it would block every product with fragrance.
          </p>
          <div className="suggest__btns">
            <Btn
              onClick={async () => {
                await api.addRecord({ type: "avoid", ingredient: "fragrance", note: "" });
                setSuggest(null);
                await refresh();
              }}
            >
              Yes, avoid fragrance
            </Btn>
            <Btn kind="ghost" onClick={() => setSuggest(null)}>
              No, just this product
            </Btn>
          </div>
        </div>
      )}

      {health?.llm && <Intake products={products} onSaved={refresh} />}

      <Section label="Add a record">
        <div className="segmented" role="radiogroup" aria-label="Record type">
          {TYPES.map((t) => (
            <button
              key={t}
              role="radio"
              aria-checked={type === t}
              className={`segmented__opt${type === t ? " is-on" : ""}`}
              onClick={() => setType(t)}
            >
              {RECORD[t].short}
            </button>
          ))}
        </div>
        <p className="formhelp">{RECORD[type].rule}</p>
        {target === "product" ? (
          <label className="field">
            <span>Which product?</span>
            <select value={productId} onChange={(e) => setProductId(e.target.value)}>
              <option value="">Choose…</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.brand})
                </option>
              ))}
            </select>
          </label>
        ) : (
          <label className="field">
            <span>Which ingredient?</span>
            <input
              value={ingredient}
              onChange={(e) => setIngredient(e.target.value)}
              placeholder="e.g. fragrance"
              list="ingredient-suggest"
            />
            <datalist id="ingredient-suggest">
              {SUGGEST.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </label>
        )}
        <label className="field">
          <span>Note (optional)</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened, roughly when" />
        </label>
        {err && <Notice tone="stop">{err}</Notice>}
        <Btn onClick={add} disabled={!canAdd || busy} wide>
          Add record
        </Btn>
      </Section>

      <div className="nextlink">
        <Btn kind="ghost" to="/compare" wide>
          Next: compare options →
        </Btn>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- free-text intake
// The AI only proposes. Each record is saved only when the user confirms it, through the
// same POST /api/history as the form; fields marked "needs confirmation" must be set by hand first.
function Intake({ products, onSaved }: { products: Product[]; onSaved: () => Promise<void> }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<IntakeResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.intake(text.trim()));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const drop = (id: string) => setRes((r) => (r ? { ...r, proposals: r.proposals.filter((p) => p.id !== id) } : r));

  return (
    <Section label="Describe it in your own words">
      <p className="formhelp">
        For example: “I broke out from a fragranced moisturiser last year and my dermat said I'm allergic to lanolin.” The AI
        suggests records; nothing is saved until you confirm each one.
      </p>
      <label className="field">
        <span>What happened?</span>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={1000} />
      </label>
      <Btn kind="ghost" onClick={run} disabled={busy || text.trim().length < 3} wide>
        {busy ? "Reading…" : "Suggest records"}
      </Btn>
      {err && <Notice tone="stop">{err}</Notice>}
      {res && (res.rejected || !res.available) && (
        <Notice tone="warn">Couldn't read that automatically. Add your records with the form below instead.</Notice>
      )}
      {res && !res.rejected && res.available && res.proposals.length === 0 && (
        <Notice tone="info">No records found in that text. You can add them with the form below.</Notice>
      )}
      {res && res.dropped > 0 && (
        <p className="small muted">
          {res.dropped} suggestion{res.dropped > 1 ? "s" : ""} didn't match your words, so {res.dropped > 1 ? "they were" : "it was"} left out.
        </p>
      )}
      {res?.proposals.map((p) => (
        <ProposalCard key={p.id} p={p} products={products} onDone={() => drop(p.id)} onSaved={onSaved} />
      ))}
    </Section>
  );
}

const NEEDS = "needs confirmation";

function ProposalCard({ p, products, onDone, onSaved }: { p: Proposal; products: Product[]; onDone: () => void; onSaved: () => Promise<void> }) {
  const [type, setType] = useState<RecordType>(p.type);
  const [productId, setProductId] = useState(p.product_id ?? "");
  const [ingredient, setIngredient] = useState(p.ingredient ?? "");
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const touch = (f: string) => setTouched((t) => new Set(t).add(f));
  const open = (f: string) => p.needs_confirmation.includes(f as Proposal["needs_confirmation"][number]) && !touched.has(f);
  const target = RECORD[type].target;
  const ready =
    !open("type") && (target === "product" ? !!productId && !open("product_id") : ingredient.trim().length > 1 && !open("ingredient"));

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.addRecord({
        type,
        product_id: target === "product" ? productId : null,
        ingredient: target === "ingredient" ? ingredient.trim() : null,
        note: p.note,
      });
      await onSaved();
      onDone();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="proposal">
      <p className="proposal__quote">“{p.quote}”</p>
      <div className="segmented" role="radiogroup" aria-label="Record type">
        {TYPES.map((t) => (
          <button
            key={t}
            role="radio"
            aria-checked={type === t}
            className={`segmented__opt${type === t ? " is-on" : ""}`}
            onClick={() => {
              setType(t);
              touch("type");
            }}
          >
            {RECORD[t].short}
          </button>
        ))}
      </div>
      {open("type") && <span className="needs">{NEEDS}: tap the right type</span>}
      {target === "product" ? (
        <label className="field">
          <span>
            Which product?{p.product_text && !p.product_matched && <> You wrote “{p.product_text}” (not in the catalog).</>}
          </span>
          <select
            value={productId}
            onChange={(e) => {
              setProductId(e.target.value);
              touch("product_id");
            }}
          >
            <option value="">Choose…</option>
            {products.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name} ({x.brand})
              </option>
            ))}
          </select>
          {open("product_id") && <span className="needs">{NEEDS}</span>}
        </label>
      ) : (
        <label className="field">
          <span>Which ingredient?</span>
          <input
            value={ingredient}
            onChange={(e) => {
              setIngredient(e.target.value);
              touch("ingredient");
            }}
          />
          {open("ingredient") && <span className="needs">{NEEDS}</span>}
        </label>
      )}
      {p.hints.map((h) => (
        <p key={h} className="small muted">
          {h}
        </p>
      ))}
      {err && <Notice tone="stop">{err}</Notice>}
      <div className="suggest__btns">
        <Btn onClick={save} disabled={!ready || busy}>
          Confirm and save
        </Btn>
        <Btn kind="ghost" onClick={onDone}>
          Skip
        </Btn>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- B2: product outcomes
const OUTCOME_VALUES: OutcomeValue[] = ["suited", "irritation", "breakout", "not_sure"];
const ZONES: FaceZone[] = ["forehead", "nose", "cheeks", "chin", "jaw"];

/**
 * What happened when you used a product (backend app/outcomes.py).
 *
 * The 4-week rule is the thing to notice here: a "suited" outcome under 4 weeks reads "too early
 * to say" on the row, because that is what the engine does with it. Nothing on this screen works
 * out that label; it comes down with the row.
 */
function Outcomes() {
  const { outcomes, catalog, products, refresh } = useStore();
  const [open, setOpen] = useState(false);

  return (
    <Section
      label={`What happened (${outcomes.length})`}
      aside={
        <button type="button" className="textbtn" onClick={() => setOpen((o) => !o)}>
          {open ? "Close" : "Add"}
        </button>
      }
    >
      <p className="formhelp">{OUTCOMES_LEDE}</p>
      <p className="small muted">{SUITED_RULE}</p>
      {outcomes.length === 0 ? (
        <p className="muted">
          Nothing recorded yet. Until there is, no ingredient can be a suspect and nothing is cleared.
        </p>
      ) : (
        <ul className="outcomes">
          {outcomes.map((o) => {
            const p = catalog[o.product_id];
            const look = OUTCOME[o.effective_outcome];
            return (
              <li key={o.id} className={`outcome outcome--${look.tone}`}>
                <span className="outcome__head">
                  <strong>{p?.name ?? o.product_id}</strong>
                  <span className={`chip chip--outcome-${o.effective_outcome}`}>{look.chip}</span>
                  <span className="small muted">{o.leave_on ? "Stays on" : "Washed off"}</span>
                  {p && !p.inci_complete && <IncompleteTag />}
                </span>
                <span className="outcome__line">{o.plain_line}</span>
                <span className="outcome__meta small muted">
                  {o.started_on ? `Started ${o.started_on}` : "Start date not recorded"}
                  {o.stopped_on ? ` · stopped ${o.stopped_on}` : o.started_on ? " · still using it" : ""}
                  {o.zones.length > 0 && ` · ${o.zones.map((z) => ZONE_LABEL[z]).join(", ")}`}
                  {o.source === "writeback" && " · written in from a trial verdict"}
                </span>
                {o.note && <span className="outcome__note">{o.note}</span>}
                <button
                  className="record__x"
                  aria-label={`Remove the record for ${p?.name ?? o.product_id}`}
                  onClick={async () => {
                    await api.removeOutcome(o.id);
                    await refresh();
                  }}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {open && (
        <OutcomeForm
          products={products}
          onSaved={async () => {
            setOpen(false);
            await refresh();
          }}
        />
      )}
    </Section>
  );
}

function OutcomeForm({ products, onSaved }: { products: Product[]; onSaved: () => Promise<void> }) {
  const [productId, setProductId] = useState("");
  const [outcome, setOutcome] = useState<OutcomeValue>("suited");
  const [startedOn, setStartedOn] = useState("");
  const [stoppedOn, setStoppedOn] = useState("");
  const [weeks, setWeeks] = useState("");
  const [zones, setZones] = useState<FaceZone[]>([]);
  const [usual, setUsual] = useState<boolean | null>(null);
  const [settled, setSettled] = useState<boolean | null>(null);
  const [settledWeek, setSettledWeek] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.addOutcome({
        product_id: productId,
        outcome,
        started_on: startedOn || null,
        stopped_on: stoppedOn || null,
        weeks_used_given: weeks ? Number(weeks) : null,
        zones: outcome === "breakout" ? zones : [],
        usual_spots: outcome === "breakout" ? usual : null,
        settled_while_using: outcome === "breakout" ? settled : null,
        settled_week: outcome === "breakout" && settledWeek ? Number(settledWeek) : null,
        note,
      });
      await onSaved();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  const tri = (
    label: string,
    value: boolean | null,
    set: (v: boolean | null) => void,
    noLabel = "No"
  ) => (
    <>
      <p className="formhelp">{label}</p>
      <div className="segmented segmented--wrap" role="radiogroup" aria-label={label}>
        {([[true, "Yes"], [false, noLabel], [null, "Not sure"]] as [boolean | null, string][]).map(([v, text]) => (
          <button
            key={String(v)}
            role="radio"
            aria-checked={value === v}
            className={`segmented__opt${value === v ? " is-on" : ""}`}
            onClick={() => set(v)}
          >
            {text}
          </button>
        ))}
      </div>
    </>
  );

  return (
    <div className="outcomeform">
      <label className="field">
        <span>Which product?</span>
        <select value={productId} onChange={(e) => setProductId(e.target.value)}>
          <option value="">Choose…</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.brand})
            </option>
          ))}
        </select>
      </label>

      <div className="segmented segmented--wrap" role="radiogroup" aria-label="What happened?">
        {OUTCOME_VALUES.map((v) => (
          <button
            key={v}
            role="radio"
            aria-checked={outcome === v}
            className={`segmented__opt${outcome === v ? " is-on" : ""}`}
            onClick={() => setOutcome(v)}
          >
            {OUTCOME[v].chip}
          </button>
        ))}
      </div>
      <p className="formhelp">{OUTCOME_HELP[outcome]}</p>

      <div className="fieldrow">
        <label className="field">
          <span>Started</span>
          <input type="date" value={startedOn} onChange={(e) => setStartedOn(e.target.value)} />
        </label>
        <label className="field">
          <span>Stopped (if you did)</span>
          <input type="date" value={stoppedOn} onChange={(e) => setStoppedOn(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Or roughly how many weeks did you use it?</span>
        <input
          type="number"
          min={0}
          max={520}
          value={weeks}
          onChange={(e) => setWeeks(e.target.value)}
          placeholder="e.g. 12"
        />
      </label>

      {outcome === "breakout" && (
        <>
          <p className="formhelp">Where were the spots?</p>
          <div className="chips">
            {ZONES.map((z) => (
              <button
                key={z}
                className={`symchip${zones.includes(z) ? " is-on" : ""}`}
                aria-pressed={zones.includes(z)}
                onClick={() => setZones((x) => (x.includes(z) ? x.filter((y) => y !== z) : [...x, z]))}
              >
                {ZONE_LABEL[z]}
              </button>
            ))}
          </div>
          {tri("Are those your usual spots?", usual, setUsual, "No, a new area")}
          {tri("Did it settle while you were still using it?", settled, setSettled)}
          {settled && (
            <label className="field">
              <span>Settled by which week?</span>
              <input
                type="number"
                min={0}
                max={104}
                value={settledWeek}
                onChange={(e) => setSettledWeek(e.target.value)}
                placeholder="e.g. 5"
              />
            </label>
          )}
        </>
      )}

      <label className="field">
        <span>Note (optional)</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened, roughly when" />
      </label>
      {err && <Notice tone="stop">{err}</Notice>}
      <Btn onClick={save} disabled={!productId || busy} wide>
        Save what happened
      </Btn>
    </div>
  );
}

// ---------------------------------------------------------------- B3: what the records add up to
/**
 * The two pattern runs, side by side and clearly apart: irritation and breakout never share a
 * suspect list. Every line here is the engine's (backend app/patterns.py), including the honest
 * "one product can't tell us" sentence when there is only one failed product.
 */
/** How many leads are worth printing beside the suspects before the list stops helping. */
const MAX_LEADS_SHOWN = 3;

const ranked = (r: PatternReport) => r.suspects.filter((s) => s.tier !== "cleared_so_far");
const shown = (r: PatternReport) => {
  const suspects = ranked(r).filter((s) => s.tier === "suspect");
  const leads = ranked(r).filter((s) => s.tier === "lead");
  return [...suspects, ...leads.slice(0, MAX_LEADS_SHOWN)];
};
const hidden = (r: PatternReport) => ranked(r).length - shown(r).length;

function Patterns() {
  const { patterns } = useStore();
  if (!patterns) return null;
  const runs = [patterns.irritation, patterns.breakout];
  if (!runs.some((r) => r.failed_products.length)) return null;

  return (
    <Section label="What your records add up to">
      <p className="formhelp">
        Two separate reads, because an itch and a breakout are different things. Rule set{" "}
        {patterns.rule_version}, ingredient families {patterns.families_version}.
      </p>
      {runs.map((r) => (
        <div key={r.kind} className="patrun">
          <p className="eyebrow">{PATTERN_KIND[r.kind].label}</p>
          <p className="small muted">{PATTERN_KIND[r.kind].sub}</p>
          <p className="patrun__headline">{r.headline}</p>

          {r.cannot_narrow && (
            <>
              <p className="patrun__cant">{r.cannot_narrow}</p>
              {r.only_in_failed.length > 0 && (
                <p className="small muted">
                  Not in anything that suited you: {r.only_in_failed.map((x) => x.display).join(", ")}.
                </p>
              )}
            </>
          )}

          {r.suspects.filter((s) => s.tier !== "cleared_so_far").length > 0 && (
            <>
              <p className="eyebrow">{PERSONAL_LABEL}</p>
              <ul className="suspects">
                {/* Suspects in full, then a few leads. With two failed labels every excipient on
                    one of them is technically a lead, so printing all of them would bury the
                    line that matters. The count below says how many are left. */}
                {shown(r)
                  .map((s) => (
                    <li key={`${s.ingredient}-${s.match_type}`} className={`suspect suspect--${s.tier}`}>
                      <span className="suspect__head">
                        <strong>{s.display}</strong>
                        <span className={`chip chip--${s.tier}`}>{TIER[s.tier].label}</span>
                        {s.match_type === "family" && <span className="tag tag--unknown">family match</span>}
                      </span>
                      <span className="suspect__counts">{s.counts_line}</span>
                      <span className="suspect__where small muted">
                        {s.in_failed
                          .map((a) => `${a.product_name}: line ${a.inci_position} of ${a.inci_length}`)
                          .join(" · ")}
                      </span>
                      {s.general_note && (
                        <span className="suspect__general">
                          <em>{GENERAL_LABEL}:</em> {s.general_note}
                        </span>
                      )}
                    </li>
                  ))}
              </ul>
            </>
          )}

          {hidden(r) > 0 && (
            <p className="small muted">
              {hidden(r)} more lead{hidden(r) === 1 ? "" : "s"} on those labels, each in one product
              that bothered you and none that suited you. Not enough on its own to call.
            </p>
          )}

          {r.suspects.some((s) => s.tier === "cleared_so_far") && (
            <p className="small muted">
              Used without this problem:{" "}
              {r.suspects
                .filter((s) => s.tier === "cleared_so_far")
                .slice(0, 6)
                .map((s) => s.display)
                .join(", ")}
              .
            </p>
          )}

          {r.unknown_note && <p className="patrun__unknown">{r.unknown_note}</p>}

          {r.purge_offers.map((o) => (
            <div key={o.product_id} className="purgeoffer">
              <p className="eyebrow">Could this have been purging?</p>
              <p>{o.question}</p>
              <p className="small muted">{o.note}</p>
              <p className="small muted">
                Nothing changes unless you say so: your record still reads as a breakout.
              </p>
            </div>
          ))}
        </div>
      ))}
    </Section>
  );
}
