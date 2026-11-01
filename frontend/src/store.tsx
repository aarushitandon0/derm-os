import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  type Health,
  type HistoryRecord,
  type Meta,
  type Patterns,
  type Product,
  type ProductOutcome,
  type Trial,
} from "./api";

interface Store {
  ready: boolean;
  error: string | null;
  /** The server didn't answer at all (asleep or down), as opposed to answering with an error. */
  unreachable: boolean;
  health: Health | null;
  meta: Meta | null;
  catalog: Record<string, Product>;
  products: Product[];
  shelf: string[];
  history: HistoryRecord[];
  /** What happened, product by product (app/outcomes.py). The memory every moment reads. */
  outcomes: ProductOutcome[];
  /** The two pattern runs, kept apart. Null until they load; they need no shelf or scan. */
  patterns: Patterns | null;
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
    unreachable: false,
    health: null,
    meta: null,
    products: [],
    shelf: [],
    history: [],
    outcomes: [],
    patterns: null,
    trials: [],
  });

  const refresh = useCallback(async () => {
    try {
      const [health, meta, products, shelf, history, trials, outcomes, patterns] = await Promise.all([
        api.health(),
        api.meta(),
        api.catalog(),
        api.shelf(),
        api.history(),
        api.trials(),
        api.outcomes(),
        // The patterns run on the outcomes alone, so they are ready before any scan.
        api.patterns().catch(() => null),
      ]);
      const active = [...trials].reverse().find((t) => t.status === "active");
      const activeBaselineCount = active
        ? await api.evidence(active.id).then((e) => e.captures.baseline.length, () => 0)
        : 0;
      setState({
        ready: true,
        error: null,
        unreachable: false,
        health,
        meta,
        products,
        shelf: shelf.product_ids,
        history,
        outcomes,
        patterns,
        trials,
        activeBaselineCount,
      });
    } catch (e) {
      const unreachable = e instanceof ApiError && e.status === 0;
      setState((s) => ({ ...s, ready: true, error: (e as Error).message, unreachable }));
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
