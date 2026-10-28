import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Health, type HistoryRecord, type Meta, type Product, type Trial } from "./api";

interface Store {
  ready: boolean;
  error: string | null;
  health: Health | null;
  meta: Meta | null;
  catalog: Record<string, Product>;
  products: Product[];
  shelf: string[];
  history: HistoryRecord[];
  trials: Trial[];
  activeTrial: Trial | null;
  /** Baseline scans saved for the active trial (decides what the "+" button opens). */
  activeBaselineCount: number;
  refresh: () => Promise<void>;
}

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<Store, "refresh" | "catalog" | "activeTrial">>({
    activeBaselineCount: 0,
    ready: false,
    error: null,
    health: null,
    meta: null,
    products: [],
    shelf: [],
    history: [],
    trials: [],
  });

  const refresh = useCallback(async () => {
    try {
      const [health, meta, products, shelf, history, trials] = await Promise.all([
        api.health(),
        api.meta(),
        api.catalog(),
        api.shelf(),
        api.history(),
        api.trials(),
      ]);
      const active = [...trials].reverse().find((t) => t.status === "active");
      const activeBaselineCount = active
        ? await api.evidence(active.id).then((e) => e.captures.baseline.length, () => 0)
        : 0;
      setState({ ready: true, error: null, health, meta, products, shelf: shelf.product_ids, history, trials, activeBaselineCount });
    } catch (e) {
      setState((s) => ({ ...s, ready: true, error: (e as Error).message }));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<Store>(() => {
    const catalog = Object.fromEntries(state.products.map((p) => [p.id, p]));
    const active = [...state.trials].reverse().find((t) => t.status === "active") ?? null;
    return { ...state, catalog, activeTrial: active, refresh };
  }, [state, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside StoreProvider");
  return s;
}
