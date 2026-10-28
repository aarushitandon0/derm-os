import { useState } from "react";
import { api, type IntakeResult, type Product, type Proposal, type RecordType } from "../api";
import { RECORD } from "../copy";
import { Btn, Notice, PageHead, Section, TopBar } from "../components/ui";
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
