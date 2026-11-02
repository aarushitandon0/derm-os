import { useCallback, useEffect, useState } from "react";
import { useAccount } from "../account";
import { ACCOUNT } from "../accountCopy";
import { isLoggedOut, meApi, type Profile as ProfileData, type SavedBasket, type SavedChip, type SavedRecord, type SavedScan } from "../api";
import { accountError, AuthForm, NewPassword } from "../components/Account";
import { StartPlanCard } from "../components/BasketExtras";
import { Btn, Loading, NavBar, Notice, PageHead, Section } from "../components/ui";
import { fmtDate, inr, NOT_DIAGNOSIS, RECORD } from "../copy";
import { go } from "../router";
import { useStore } from "../store";

interface Data {
  profile: ProfileData;
  chips: SavedChip[];
  records: SavedRecord[];
  catalogue: { id: string; label: string }[];
  reactions: Record<string, string>;
  shelf: string[];
  baskets: SavedBasket[];
  scans: SavedScan[];
}

/** #/login: log in or sign up. Already logged in: straight to the profile. */
export function Login() {
  const a = useAccount();
  useEffect(() => {
    if (a.session && !a.recovering) go("/profile");
  }, [a.session, a.recovering]);
  return (
    <div className="page">
      <NavBar back="/" />
      <PageHead title={ACCOUNT.loginTitle} lede={ACCOUNT.loginLede} />
      {!a.enabled ? <Notice>{ACCOUNT.notSetUp}</Notice> : <><NewPassword /><AuthForm onDone={() => go("/profile")} /></>}
    </div>
  );
}

export default function Profile() {
  const a = useAccount();
  const { catalog, products } = useStore();
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [openBasket, setOpenBasket] = useState<string | null>(null);

  // Every call gets a fresh token; a 401 asks for a log-in, a sleeping server just says so.
  const withToken = useCallback(
    async <T,>(fn: (t: string) => Promise<T>): Promise<T | undefined> => {
      setErr(null);
      try {
        const t = await a.token();
        if (!t) {
          setNeedLogin(true);
          return undefined;
        }
        return await fn(t);
      } catch (e) {
        if (isLoggedOut(e)) setNeedLogin(true);
        setErr(accountError(e));
        return undefined;
      }
    },
    [a]
  );

  const load = useCallback(async () => {
    const d = await withToken(async (t) => {
      const [me, h, s, b, sc] = await Promise.all([
        meApi.get(t),
        meApi.history(t),
        meApi.shelf(t),
        meApi.baskets(t),
        meApi.scans(t),
      ]);
      return { profile: me.profile, chips: h.chips, records: h.records, catalogue: h.catalogue, reactions: h.reactions,
               shelf: s.product_ids, baskets: b, scans: sc.scans };
    });
    if (d) {
      setData(d);
      setNeedLogin(false);
    }
  }, [withToken]);

  useEffect(() => {
    if (a.ready && a.session) void load();
  }, [a.ready, a.session, load]);

  if (!a.enabled)
    return (
      <div className="page">
        <NavBar back="/" />
        <PageHead title={ACCOUNT.title} />
        <Notice>{ACCOUNT.notSetUp}</Notice>
      </div>
    );
  if (!a.ready) return <div className="page"><NavBar back="/" /><Loading /></div>;
  if (!a.session || needLogin)
    return (
      <div className="page">
        <NavBar back="/" />
        <PageHead title={ACCOUNT.title} lede={needLogin ? ACCOUNT.loggedOut : ACCOUNT.loginLede} />
        <AuthForm onDone={() => { setNeedLogin(false); void load(); }} />
      </div>
    );

  const flash = (m: string) => {
    setNote(m);
    window.setTimeout(() => setNote(null), 2500);
  };

  const download = async () => {
    const body = await withToken((t) => meApi.exportData(t));
    if (!body) return;
    const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
    const u = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = u;
    el.download = "dermos-my-data.json";
    el.click();
    URL.revokeObjectURL(u);
  };

  const removeAccount = async () => {
    if (!window.confirm(ACCOUNT.deleteConfirm)) return;
    setBusy(true);
    const r = await withToken((t) => meApi.deleteAccount(t));
    setBusy(false);
    if (r?.deleted) {
      await a.signOut().catch(() => undefined);
      window.alert(ACCOUNT.deleted);
      go("/");
    }
  };

  return (
    <div className="page page--wide profile">
      <NavBar back="/" right={<button type="button" className="textbtn" onClick={() => a.signOut().then(() => go("/"))}>{ACCOUNT.logOut}</button>} />
      <PageHead title={ACCOUNT.title} eyebrow={a.email ?? undefined} lede={ACCOUNT.photoLine} />
      <NewPassword />
      {err && (
        <Notice tone="warn">
          {err}{" "}
          <button type="button" className="textbtn" onClick={load}>
            {ACCOUNT.retry}
          </button>
        </Notice>
      )}
      {note && <p className="small" role="status">{note}</p>}
      {!data && !err && <Loading />}
      {data && (
        <div className="profile__grid">
          <div className="profile__col">
            <Details profile={data.profile} onSave={async (p) => {
              const r = await withToken((t) => meApi.setProfile(t, p));
              if (r) { setData({ ...data, profile: r }); flash(ACCOUNT.savedShort); }
            }} />

            <Section label={ACCOUNT.historyLabel}>
              <p className="formhelp">{ACCOUNT.historyHelp}</p>
              <h3 className="profile__sub">{ACCOUNT.chipsLabel}</h3>
              <ChipsEditor data={data} onChange={async (chips) => {
                const r = await withToken((t) => meApi.setChips(t, chips));
                if (r) setData({ ...data, chips: r.chips });
              }} />
              <h3 className="profile__sub">{ACCOUNT.recordsLabel}</h3>
              <RecordsEditor
                records={data.records}
                products={products.map((p) => ({ id: p.id, name: `${p.brand} ${p.name}` }))}
                name={(id) => (catalog[id] ? `${catalog[id].brand} ${catalog[id].name}` : id)}
                onAdd={async (r) => {
                  const row = await withToken((t) => meApi.addRecord(t, r));
                  if (row) setData({ ...data, records: [...data.records, row] });
                }}
                onRemove={async (id) => {
                  const ok = await withToken((t) => meApi.removeRecord(t, id));
                  if (ok !== undefined) setData({ ...data, records: data.records.filter((x) => x.id !== id) });
                }}
              />
            </Section>

            <Section label={ACCOUNT.shelfLabel}>
              <ShelfEditor
                ids={data.shelf}
                products={products.map((p) => ({ id: p.id, name: `${p.brand} ${p.name}` }))}
                onChange={async (ids) => {
                  const r = await withToken((t) => meApi.setShelf(t, ids));
                  if (r) setData({ ...data, shelf: r.product_ids });
                }}
              />
            </Section>
          </div>

          <div className="profile__col">
            <Section label={ACCOUNT.basketsLabel}>
              {data.baskets.length === 0 && <p className="small muted">{ACCOUNT.noBaskets}</p>}
              <ul className="savedlist">
                {data.baskets.map((b) => (
                  <li key={b.id} className="saved">
                    <div className="saved__head">
                      <span className="saved__title">
                        {fmtDate(b.created_at)} · {inr(b.basket.total_inr ?? 0)}
                        {b.demo && <span className="tag tag--prepared saved__tag">{ACCOUNT.demoTag}</span>}
                      </span>
                      <span className="saved__btns">
                        <button type="button" className="textbtn" onClick={() => setOpenBasket(openBasket === b.id ? null : b.id)}>
                          {openBasket === b.id ? ACCOUNT.hide : ACCOUNT.open}
                        </button>
                        <button type="button" className="textbtn" onClick={async () => {
                          const ok = await withToken((t) => meApi.removeBasket(t, b.id));
                          if (ok !== undefined) setData({ ...data, baskets: data.baskets.filter((x) => x.id !== b.id) });
                        }}>
                          {ACCOUNT.remove}
                        </button>
                      </span>
                    </div>
                    <p className="small muted">{b.basket.face_map?.needs_line}</p>
                    {openBasket === b.id && (
                      <div className="saved__body">
                        <ul className="srclines">
                          {(b.basket.jobs ?? []).map((j) => (
                            <li key={`${j.job}-${j.zone}`}>
                              <strong>{j.title}</strong>
                              {j.pick ? `: ${j.pick.product.brand} ${j.pick.product.name}` : ""}
                            </li>
                          ))}
                        </ul>
                        {b.start_plan && <StartPlanCard plan={b.start_plan} demo={b.demo} />}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </Section>

            <Section label={ACCOUNT.scansLabel}>
              <p className="formhelp">{ACCOUNT.photoLine}</p>
              {data.scans.length === 0 && <p className="small muted">{ACCOUNT.noScans}</p>}
              <ul className="savedlist">
                {data.scans.map((s) => (
                  <li key={s.id} className="saved">
                    <span className="saved__title">{fmtDate(s.created_at)}</span>
                    <p className="small">
                      {Object.entries(s.zone_types).map(([z, t]) => `${ACCOUNT.zones[z] ?? z}: ${t}`).join(" · ")}
                    </p>
                    {s.undertone && (
                      <p className="small muted">
                        Undertone: {s.undertone} ({s.undertone_method})
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </Section>

            <Section label={ACCOUNT.dataLabel}>
              <div className="actions">
                <Btn kind="ghost" wide onClick={download}>
                  {ACCOUNT.download}
                </Btn>
                <Btn kind="danger" wide onClick={removeAccount} disabled={busy}>
                  {busy ? ACCOUNT.wait : ACCOUNT.deleteAccount}
                </Btn>
              </div>
            </Section>
          </div>
        </div>
      )}
      <p className="foot small">{NOT_DIAGNOSIS} All products shown are fictional.</p>
    </div>
  );
}

function Details({ profile, onSave }: { profile: ProfileData; onSave: (p: Pick<ProfileData, "display_name" | "finish_goal" | "budget" | "beginner">) => Promise<void> }) {
  const [name, setName] = useState(profile.display_name);
  const [finish, setFinish] = useState(profile.finish_goal ?? "");
  const [budget, setBudget] = useState(profile.budget ?? "");
  const [beginner, setBeginner] = useState(profile.beginner);
  return (
    <Section label={ACCOUNT.detailsLabel}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void onSave({
            display_name: name,
            finish_goal: (finish || null) as ProfileData["finish_goal"],
            budget: (budget || null) as ProfileData["budget"],
            beginner,
          });
        }}
      >
        <label className="field">
          <span>{ACCOUNT.name}</span>
          <input value={name} maxLength={60} autoComplete="given-name" onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>{ACCOUNT.finish}</span>
          <select value={finish} onChange={(e) => setFinish(e.target.value)}>
            <option value="">—</option>
            {Object.entries(ACCOUNT.finishes).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{ACCOUNT.budget}</span>
          <select value={budget} onChange={(e) => setBudget(e.target.value)}>
            <option value="">—</option>
            {Object.entries(ACCOUNT.budgets).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <label className="checkrow">
          <input type="checkbox" checked={beginner} onChange={(e) => setBeginner(e.target.checked)} />
          <span>{ACCOUNT.beginner}</span>
        </label>
        <Btn type="submit" kind="ghost" wide>
          {ACCOUNT.save}
        </Btn>
      </form>
    </Section>
  );
}

function ChipsEditor({ data, onChange }: { data: Data; onChange: (c: SavedChip[]) => Promise<void> }) {
  const [chip, setChip] = useState("");
  const [reaction, setReaction] = useState("");
  const label = (id: string) => data.catalogue.find((c) => c.id === id)?.label ?? id.replace(/^free:/, "");
  return (
    <>
      {data.chips.length === 0 && <p className="small muted">{ACCOUNT.noHistory}</p>}
      <ul className="editlist">
        {data.chips.map((c) => (
          <li key={c.id}>
            <span>
              {label(c.chip)}: {data.reactions[c.reaction] ?? c.reaction}
              {c.clinician_confirmed && <span className="tag saved__tag">{ACCOUNT.clinician}</span>}
            </span>
            <button type="button" className="textbtn" onClick={() => onChange(data.chips.filter((x) => x.id !== c.id))}>
              {ACCOUNT.remove}
            </button>
          </li>
        ))}
      </ul>
      <div className="addrow">
        <select aria-label={ACCOUNT.addChip} value={chip} onChange={(e) => setChip(e.target.value)}>
          <option value="">{ACCOUNT.addChip}…</option>
          {data.catalogue.map((c) => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>
        <select aria-label="What happened" value={reaction} onChange={(e) => setReaction(e.target.value)}>
          <option value="">What happened…</option>
          {Object.entries(data.reactions).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <Btn kind="ghost" disabled={!chip || !reaction} onClick={() => {
          void onChange([...data.chips.filter((x) => x.chip !== chip),
            { chip, reaction, product_name: "", confirmed_allergy: false, usual_spots_settled: null, purge_choice: null } as SavedChip]);
          setChip("");
          setReaction("");
        }}>
          Add
        </Btn>
      </div>
    </>
  );
}

function RecordsEditor({ records, products, name, onAdd, onRemove }: {
  records: SavedRecord[];
  products: { id: string; name: string }[];
  name: (id: string) => string;
  onAdd: (r: { type: SavedRecord["type"]; product_id: string | null; ingredient: string | null; note: string; clinician_confirmed: boolean }) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
}) {
  const [type, setType] = useState<SavedRecord["type"]>("avoid");
  const [pid, setPid] = useState("");
  const [ing, setIng] = useState("");
  const [clin, setClin] = useState(false);
  const target = RECORD[type].target;
  const ready = target === "product" ? !!pid : ing.trim().length > 1;
  return (
    <>
      {records.length === 0 && <p className="small muted">{ACCOUNT.noHistory}</p>}
      <ul className="editlist">
        {records.map((r) => (
          <li key={r.id}>
            <span>
              {RECORD[r.type].short}: {r.product_id ? name(r.product_id) : r.ingredient}
              {r.clinician_confirmed && <span className="tag saved__tag">{ACCOUNT.clinician}</span>}
            </span>
            <button type="button" className="textbtn" onClick={() => onRemove(r.id)}>
              {ACCOUNT.remove}
            </button>
          </li>
        ))}
      </ul>
      <div className="addrow">
        <select aria-label="Kind" value={type} onChange={(e) => setType(e.target.value as SavedRecord["type"])}>
          {(Object.keys(RECORD) as SavedRecord["type"][]).map((k) => (
            <option key={k} value={k}>{RECORD[k].label}</option>
          ))}
        </select>
        {target === "product" ? (
          <select aria-label="Which product" value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">Which product…</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        ) : (
          <input aria-label="Which ingredient" placeholder="Which ingredient" value={ing} onChange={(e) => setIng(e.target.value)} />
        )}
        <label className="checkrow">
          <input type="checkbox" checked={clin || type === "confirmed_allergy"} disabled={type === "confirmed_allergy"} onChange={(e) => setClin(e.target.checked)} />
          <span>{ACCOUNT.clinician}</span>
        </label>
        <Btn kind="ghost" disabled={!ready} onClick={() => {
          void onAdd({ type, product_id: target === "product" ? pid : null, ingredient: target === "product" ? null : ing.trim(),
                       note: "", clinician_confirmed: clin || type === "confirmed_allergy" });
          setPid("");
          setIng("");
          setClin(false);
        }}>
          {ACCOUNT.addRecord}
        </Btn>
      </div>
    </>
  );
}

function ShelfEditor({ ids, products, onChange }: { ids: string[]; products: { id: string; name: string }[]; onChange: (ids: string[]) => Promise<void> }) {
  const [pick, setPick] = useState("");
  const nameOf = (id: string) => products.find((p) => p.id === id)?.name ?? id;
  return (
    <>
      {ids.length === 0 && <p className="small muted">{ACCOUNT.noShelf}</p>}
      <ul className="editlist">
        {ids.map((id) => (
          <li key={id}>
            <span>{nameOf(id)}</span>
            <button type="button" className="textbtn" onClick={() => onChange(ids.filter((x) => x !== id))}>
              {ACCOUNT.remove}
            </button>
          </li>
        ))}
      </ul>
      <div className="addrow">
        <select aria-label={ACCOUNT.addProduct} value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">{ACCOUNT.addProduct}…</option>
          {products.filter((p) => !ids.includes(p.id)).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <Btn kind="ghost" disabled={!pick} onClick={() => { void onChange([...ids, pick]); setPick(""); }}>
          Add
        </Btn>
      </div>
    </>
  );
}
