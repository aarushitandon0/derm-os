import { useEffect, useState } from "react";
import { api, type CartCheck, type SaleItem } from "../api";
import {
  CART_LEDE,
  CART_RUNG,
  CHANGE_NOTHING_LABEL,
  EXACT_VS_FAMILY,
  GENERAL_LABEL,
  inr,
  NEXT_STEP_LABEL,
  NOT_DIAGNOSIS,
  SOURCE_HELP,
} from "../copy";
import { Btn, IncompleteTag, Loading, Notice, PageHead, Section } from "../components/ui";
import { useStore } from "../store";

/**
 * One product's cart check (backend app/cartcheck.py), as the verdict ladder, the three labelled
 * sources, "change nothing", and exactly one next step.
 *
 * Nothing on this panel is worked out here. Every sentence, including the verdict line and the
 * next step, comes from the backend, so the wording ceiling is enforced in one place and the
 * claim linter can check it.
 */
export function CartCheckPanel({
  productId,
  saleItem,
  onBack,
}: {
  productId: string;
  saleItem?: SaleItem;
  onBack?: () => void;
}) {
  const { catalog, refresh } = useStore();
  const [res, setRes] = useState<CartCheck | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const p = catalog[productId];

  useEffect(() => {
    setRes(null);
    api.cartCheck(productId).then(setRes, (e) => setErr((e as Error).message));
  }, [productId]);

  if (err) return <Notice tone="stop">{err}</Notice>;
  if (!res) return <Loading label="Checking it against your skin and your history" />;

  const tone = CART_RUNG[res.rung].tone;
  const startTrial = async () => {
    setStarting(true);
    try {
      await api.startTrial({
        goal_concern: p?.aimed_at?.[0] ?? "pore",
        product_id: productId,
        held_fixed: [],
      });
      await refresh();
      window.location.hash = "/routine";
    } catch (e) {
      setErr((e as Error).message);
      setStarting(false);
    }
  };

  return (
    <>
      <PageHead
        eyebrow={p ? `${p.brand} · ${p.name}` : productId}
        title={res.verdict_line}
        lede={CART_LEDE}
      />
      {saleItem && (
        <p className="small muted">
          On sale at {inr(saleItem.sale_price_inr)}, normally {inr(saleItem.product.price_inr)}.
        </p>
      )}
      <section className={`standout standout--${res.unknown ? "unsure" : tone}`} aria-live="polite">
        {/* The kicker says what the verdict line says. An unreadable label can't also read as
            "no conflicts", so on an unknown it is the unknown that leads here too. */}
        <p className="standout__kicker">{res.unknown ? res.verdict_line : CART_RUNG[res.rung].kicker}</p>
        {res.tags.includes("ingredient_list_incomplete") && <IncompleteTag />}
      </section>

      {res.sources.map((s) => (
        <Section key={s.key} label={s.label}>
          <p className="formhelp">{SOURCE_HELP[s.key]}</p>
          <ul className="srclines">
            {s.lines.map((ln, i) => (
              <li key={i}>{ln}</li>
            ))}
          </ul>
          {s.key === "history" && <HistoryDetail detail={s.detail} />}
          {s.key === "skin" && Array.isArray(s.detail?.top_concerns) && s.detail.top_concerns.length > 0 && (
            <p className="small muted">
              Measured concerns, worst first: {s.detail.top_concerns.join(", ")}.
            </p>
          )}
        </Section>
      ))}

      <Section label={NEXT_STEP_LABEL}>
        <p className="prose">{res.next_step}</p>
        <div className="actions">
          {res.rung !== "blocked" && (
            <Btn onClick={startTrial} disabled={starting} wide>
              {starting ? "Opening…" : "Start it as my only new product"}
            </Btn>
          )}
          {onBack && (
            <Btn kind="ghost" onClick={onBack} wide>
              Back to the sale
            </Btn>
          )}
        </div>
      </Section>

      <Section label={CHANGE_NOTHING_LABEL}>
        <p className="prose">{res.change_nothing}</p>
      </Section>

      <p className="foot small">
        {NOT_DIAGNOSIS} Rule set {res.rule_version}.
      </p>
    </>
  );
}

/** The matched label lines in full, with where each one came from. Personal and general kept apart. */
function HistoryDetail({ detail }: { detail: Record<string, any> }) {
  const matches: any[] = Array.isArray(detail?.matches) ? detail.matches : [];
  const general: string[] = Array.isArray(detail?.general_knowledge) ? detail.general_knowledge : [];
  if (!matches.length && !general.length) return null;
  return (
    <>
      {matches.length > 0 && (
        <table className="conds">
          <thead>
            <tr>
              <th>Label line</th>
              <th>How it matched</th>
              <th>Your records</th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m, i) => (
              <tr key={i}>
                <th>{m.label_line}</th>
                <td>
                  {m.tier === "suspect" ? "Suspect" : "Lead"} · {EXACT_VS_FAMILY[m.match_type as "exact" | "family"]}
                </td>
                <td>{m.counts_line}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {general.length > 0 && (
        <div className="general">
          <p className="eyebrow">{GENERAL_LABEL}</p>
          {general.map((g) => (
            <p key={g} className="small muted">
              {g}
            </p>
          ))}
        </div>
      )}
    </>
  );
}
