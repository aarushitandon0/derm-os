import { useEffect, useState } from "react";
import { api, type Role } from "../api";
import { inr, ROLE_LABEL } from "../copy";
import { Btn, Notice, PageHead, TopBar } from "../components/ui";
import { go } from "../router";
import { useStore } from "../store";

const ROLES: Role[] = ["cleanser", "toner", "serum", "treatment", "moisturiser", "sunscreen"];

export default function Shelf() {
  const { products, shelf, refresh } = useStore();
  const [sel, setSel] = useState<string[]>(shelf);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setSel(shelf), [shelf]);

  const toggle = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const dirty = sel.join() !== shelf.join();

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      await api.setShelf(sel);
      await refresh();
      go("/history");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <TopBar title="Shelf" />
      <PageHead
        title="What you use now."
        lede="Pick the products already in your routine. Everything else is compared against this."
      />
      {ROLES.map((role) => {
        const items = products.filter((p) => p.role === role);
        if (!items.length) return null;
        return (
          <section key={role} className="shelfgroup">
            <h2 className="section__label">{ROLE_LABEL[role]}</h2>
            <ul className="picklist">
              {items.map((p) => {
                const on = sel.includes(p.id);
                return (
                  <li key={p.id}>
                    <button className={`pick${on ? " is-on" : ""}`} onClick={() => toggle(p.id)} aria-pressed={on}>
                      <span className="pick__box" aria-hidden />
                      <span className="pick__body">
                        <span className="pick__name">{p.name}</span>
                        <span className="pick__meta">
                          {p.brand} · {inr(p.price_inr)} · {p.leave_on ? "leave-on" : "wash-off"}
                          {!p.inci_complete && <span className="tag tag--unknown">incomplete label</span>}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      {err && <Notice tone="stop">{err}</Notice>}
      <div className="stickybar">
        <span className="mono">{sel.length} selected</span>
        <Btn onClick={save} disabled={saving || (!dirty && shelf.length === 0)}>
          {saving ? "Saving…" : dirty ? "Save shelf" : "Next: history"}
        </Btn>
      </div>
    </div>
  );
}
