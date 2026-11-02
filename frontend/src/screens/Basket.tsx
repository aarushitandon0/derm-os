import { useEffect, useRef, useState } from "react";
import {
  api,
  assetUrl,
  meApi,
  type Basket as BasketData,
  type BasketJob,
  type BasketQuestion,
  type Profile as ProfileData,
  type ProfileUse,
  type SavedChip,
  type SavedRecord,
} from "../api";
import { ACCOUNTS_ENABLED, useAccount } from "../account";
import { ACCOUNT } from "../accountCopy";
import { BASKET } from "../basketCopy";
import { DEMO_DATA_TAG, inr, NOT_DIAGNOSIS, RECORD } from "../copy";
import { FaceMap } from "../components/FaceMap";
import { artFor, ProductArt } from "../components/ProductArt";
import { Icon } from "../components/Icon";
import { Btn, IncompleteTag, Loading, NavBar, Notice, PageHead, RowLink, Section } from "../components/ui";
import { ChipsPicker, LookFor, PasteCheck, StartPlanCard } from "../components/BasketExtras";
import { accountError, SaveBasketCard } from "../components/Account";
import { KEYS, writeLocal } from "../local";
import { href } from "../router";
import { useStore } from "../store";

type Step = "start" | "questions" | "result" | "tryon";

/**
 * The hero flow (docs/strategy.md section 4): face -> three questions -> face map -> basket ->
 * try-on -> one next step. Every sentence comes from the backend engines, so the wording rules
 * live in one place; this screen lays them out.
 */
export default function Basket({ autoDemo = null }: { autoDemo?: string | null }) {
  const { health, refresh, catalog } = useStore();
  const [step, setStep] = useState<Step>("start");
  const [questions, setQuestions] = useState<BasketQuestion[] | null>(null);
  const [onRecord, setOnRecord] = useState<{ records: number; outcomes: number; bothered: number } | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({ finish: "dewy", history: "use", budget: "any" });
  const [photo, setPhoto] = useState<File | null>(null);
  const [demoFace, setDemoFace] = useState(false);
  const [persona, setPersona] = useState<"riya" | "beginner">("riya");
  const [basket, setBasket] = useState<BasketData | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const demo = !!health?.demo_mode;
  // Logged in: the questions start from the saved profile. Changes stay with this basket unless
  // "Update my profile too" is ticked. Riya and Beginner stay demo personas: they never read it.
  const acct = useAccount();
  const loggedIn = ACCOUNTS_ENABLED && !!acct.session;
  const [mine, setMine] = useState<MyProfile | null>(null);
  const [prefilled, setPrefilled] = useState<Record<string, string>>({});
  const [use, setUse] = useState<ProfileUse>({ chips: [], records: [], shelf: [] });
  const [updateProfile, setUpdateProfile] = useState(false);

  const [loadingMine, setLoadingMine] = useState(false);
  const startFromProfile = async (selfie: File | null) => {
    setBusy(true);
    setLoadingMine(true);
    setErr(null);
    try {
      const t = await acct.token();
      if (!t) throw new Error(ACCOUNT.loggedOut);
      const [me, h, sh] = await Promise.all([meApi.get(t), meApi.history(t), meApi.shelf(t)]);
      const p = me.profile;
      const pre: Record<string, string> = { history: p.beginner ? "new" : "use" };
      if (p.finish_goal) pre.finish = p.finish_goal;
      if (p.budget) pre.budget = p.budget;
      setMine({
        profile: p,
        chips: h.chips,
        records: h.records,
        shelf: sh.product_ids,
        chipLabel: Object.fromEntries(h.catalogue.map((c) => [c.id, c.label])),
        reactions: h.reactions,
      });
      setPrefilled(pre);
      setAnswers({ finish: "dewy", budget: "any", ...pre });
      setUse({ chips: h.chips.map((c) => c.id), records: h.records.map((r) => r.id), shelf: sh.product_ids });
      setUpdateProfile(false);
      setPersona("riya");
      setDemoFace(!selfie);
      setPhoto(selfie);
      setStep("questions");
    } catch (e) {
      setErr(accountError(e));
    } finally {
      setBusy(false);
      setLoadingMine(false);
    }
  };

  useEffect(() => {
    if (step !== "questions") return;
    api.basketQuestions().then(
      (q) => {
        setQuestions(q.questions);
        setOnRecord(q.on_record);
      },
      (e) => setErr((e as Error).message)
    );
  }, [step]);

  const useDemoFace = async (who: "riya" | "beginner") => {
    setBusy(true);
    setErr(null);
    try {
      writeLocal(KEYS.onboarded, true);
      setMine(null);
      // Riya: her saved history, chips and shelf. Beginner: the scene clears the demo history first,
      // so nothing from an earlier take leaks into a "nothing tried yet" basket.
      if (health?.server_demo_mode !== false) {
        await api.demoScene(who === "riya" ? "riya-basket" : "beginner");
        await refresh();
      }
      setPersona(who);
      setAnswers((a) => ({
        ...a,
        history: who === "beginner" ? "new" : "use",
        finish: who === "beginner" ? "natural" : "dewy",
      }));
      setDemoFace(true);
      setPhoto(null);
      setStep("questions");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Home's demo-face links open here with ?demo=riya or ?demo=beginner: skip straight to the questions.
  const autoRan = useRef(false);
  useEffect(() => {
    if (autoRan.current || (autoDemo !== "riya" && autoDemo !== "beginner")) return;
    autoRan.current = true;
    void useDemoFace(autoDemo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoDemo]);

  const build = async () => {
    setBusy(true);
    setErr(null);
    try {
      let b: BasketData;
      if (mine) {
        const t = await acct.token();
        if (!t) throw new Error(ACCOUNT.loggedOut);
        if (photo && !demoFace) {
          if (updateProfile) await meApi.setProfile(t, profileFrom(mine.profile, answers));
          b = await meApi.basketScan(t, photo, answers, use);
        } else b = await meApi.basket(t, { answers, use, update_profile: updateProfile });
      } else
        b = demoFace || !photo ? await api.basket(answers, persona) : await api.basketScan(photo, answers, persona);
      setBasket(b);
      setStep("result");
      window.scrollTo(0, 0);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (step === "start")
    return (
      <div className="page page--wide">
        <NavBar back="/" />
        <div className="split">
          <div className="split__aside">
            <PageHead eyebrow={BASKET.usp} title={BASKET.hero} lede={BASKET.heroSub} />
          </div>
          <div className="split__main">
        <Section label={BASKET.startTitle}>
          <div className="choices">
            {loggedIn && (
              <RowLink
                icon="search"
                title={ACCOUNT.fromProfileRow}
                sub={ACCOUNT.fromProfileRowSub}
                onClick={() => startFromProfile(null)}
              />
            )}
            <RowLink icon="search" title={BASKET.demoFace} sub={BASKET.demoFaceSub} onClick={() => useDemoFace("riya")} />
            <RowLink
              icon="search"
              title={BASKET.beginnerFace}
              sub={BASKET.beginnerFaceSub}
              onClick={() => useDemoFace("beginner")}
            />
            {!demo && (
              <label className="pickphoto">
                <span className="pickphoto__title">{BASKET.selfie}</span>
                <span className="pickphoto__sub">{photo ? photo.name : BASKET.selfieSub}</span>
                <input
                  type="file"
                  accept="image/jpeg,image/png"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    if (f && loggedIn) return void startFromProfile(f);
                    setMine(null);
                    setPhoto(f);
                    setDemoFace(false);
                    if (f) setStep("questions");
                  }}
                />
              </label>
            )}
          </div>
          {demo && <p className="small muted">{BASKET.demoNote}</p>}
        </Section>
        {busy && <Loading label={loadingMine ? ACCOUNT.loadingProfile : "Loading the demo history"} />}
        {err && <Notice tone="stop">{err}</Notice>}
          </div>
        </div>
        <p className="foot small">{NOT_DIAGNOSIS} All products shown are fictional.</p>
      </div>
    );

  if (step === "questions")
    return (
      <div className="page page--wide">
        <NavBar
          back={null}
          left={
            <button className="iconbtn" onClick={() => setStep("start")} aria-label="Back">
              <Icon name="back" />
            </button>
          }
        />
        {demoFace && (
          <p className="tag tag--prepared">
            {DEMO_DATA_TAG} · {persona === "riya" ? "Riya" : "Beginner"}
          </p>
        )}
        <PageHead title={BASKET.questionsTitle} />
        {!questions ? (
          <Loading label="Loading the questions" />
        ) : (
          <div className="qgrid">
          {questions.map((q) => (
            <Section key={q.id} label={q.text} className={`qgrid__item qgrid__item--${q.id}`}>
              <p className="formhelp">{q.why}</p>
              {mine && prefilled[q.id] !== undefined && (
                <p className={`tag ${answers[q.id] === prefilled[q.id] ? "tag--profile" : "tag--prepared"}`}>
                  {answers[q.id] === prefilled[q.id] ? ACCOUNT.fromProfile : ACCOUNT.changedHere}
                </p>
              )}
              {q.id === "history" && mine && (
                <ProfileItems mine={mine} use={use} setUse={setUse} showHistory={answers.history !== "ignore"} />
              )}
              {q.id === "history" && !mine && onRecord && (
                <p className="small">
                  {onRecord.outcomes || onRecord.records
                    ? `On record: ${onRecord.bothered} product${onRecord.bothered === 1 ? "" : "s"} that bothered you, ${
                        onRecord.records
                      } saved note${onRecord.records === 1 ? "" : "s"}. `
                    : "Nothing saved yet. "}
                  <a href={href("/history")}>Add or review</a>
                </p>
              )}
              {q.id === "history" && !mine && answers.history === "use" && (
                <>
                  <p className="small">{BASKET.chipsHelp}</p>
                  <ChipsPicker />
                </>
              )}
              {q.id === "history" && answers.history === "new" && <p className="small">{BASKET.beginnerHelp}</p>}
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
          </div>
        )}
        {mine && questions && (
          <label className="checkrow updateprofile">
            <input type="checkbox" checked={updateProfile} onChange={(e) => setUpdateProfile(e.target.checked)} />
            <span>
              {ACCOUNT.updateProfile}
              <span className="small muted updateprofile__help">{ACCOUNT.updateProfileHelp}</span>
            </span>
          </label>
        )}
        {err && <Notice tone="stop">{err}</Notice>}
        <div className="actions actions--bar">
          <Btn onClick={build} disabled={busy || !questions} wide>
            {busy ? BASKET.building : BASKET.build}
          </Btn>
        </div>
        <p className="foot small">{NOT_DIAGNOSIS}</p>
      </div>
    );

  if (!basket)
    return (
      <div className="page page--center">
        <Loading label={BASKET.building} />
      </div>
    );

  if (step === "tryon") return <TryOnView basket={basket} onBack={() => setStep("result")} />;

  const fm = basket.face_map;
  return (
    <div className="page page--wide">
      <NavBar back="/" />
      {(fm.demo || basket.source === "replay") && (
        <p className="tag tag--prepared">{basket.demo_label ?? DEMO_DATA_TAG} · fictional shop and products</p>
      )}
      {basket.from_profile && <p className="tag tag--profile">{ACCOUNT.builtFromProfile}</p>}
      {basket.notice && <Notice tone="warn">{basket.notice}</Notice>}
      <div className="bresult">
      <aside className="bresult__map" aria-label={BASKET.faceMapLabel}>
        <PageHead eyebrow={BASKET.usp} title={BASKET.faceMapLabel} lede={fm.needs_line} />
        <FaceMap map={fm} />
        {fm.see_doctor && <p className="small">{fm.see_doctor}</p>}
        <p className="small muted">{fm.undertone.note}</p>
      </aside>

      <div className="bresult__main">
      <Section label={BASKET.basketLabel} aside={<span className="small">{BASKET.total}: {inr(basket.total_inr)}</span>}>
        <ul className="bcards">
          {basket.jobs.map((j) => (
            <JobCard key={`${j.job}-${j.zone}`} job={j} />
          ))}
        </ul>
        <div className="actions">
          <Btn onClick={() => setStep("tryon")} wide kind="ghost">
            {BASKET.tryonButton}
          </Btn>
        </div>
      </Section>

      {basket.skipped.length > 0 && (
        <Section label={BASKET.skippedLabel}>
          <ul className="skips">
            {basket.skipped.map((s) => (
              <li key={s.product_id} className={`skip skip--${s.kind}`}>
                <span className="skip__art">
                  <ProductArt product={artFor(catalog, s.product_id, s)} size={44} />
                </span>
                <span className="skip__body">
                  <span className="skip__name">
                    {s.brand} {s.name}
                  </span>
                  <span className="skip__kind">{s.label}</span>
                  <span className="skip__reason">{s.reason}</span>
                  {s.all_reasons && s.all_reasons.length > 1 && (
                    <span className="skip__more">Also: {s.all_reasons.slice(1).join(" ")}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {basket.already_own.length > 0 && (
        <Section label={BASKET.ownLabel}>
          <ul className="srclines">
            {basket.already_own.map((o) => (
              <li key={o.product_id}>{o.line}</li>
            ))}
          </ul>
        </Section>
      )}

      <Section label={BASKET.nextLabel}>
        <p className="prose nextstep">{basket.next_step}</p>
      </Section>

      <Section label={basket.start_plan.title}>
        <StartPlanCard plan={basket.start_plan} demo={basket.source === "replay"} />
        <SaveBasketCard basketId={basket.id} demo={!!fm.demo || basket.source === "replay"} />
      </Section>

      <Section label={BASKET.pasteLabel}>
        <p className="formhelp">{BASKET.pasteHelp}</p>
        <PasteCheck />
        <div className="actions">
          <Btn to="/store" kind="quiet" wide>
            {BASKET.storeLink}
          </Btn>
        </div>
      </Section>
      </div>
      </div>

      <p className="foot small">
        {NOT_DIAGNOSIS} Skin type and concerns by YouCam AI Skin Analysis, colour by YouCam AI Facial Color Tones
        Analyzer. Rule set {basket.rule_version}. All products shown are fictional.
      </p>
    </div>
  );
}

function JobCard({ job }: { job: BasketJob }) {
  const p = job.pick?.product;
  return (
    <li className={`bcard bcard--${job.status}`}>
      <p className="bcard__job">{job.title}</p>
      {job.label && <p className="bcard__label">{job.label}</p>}
      {p ? (
        <div className="bcard__head">
          <span className="bcard__art">
            <ProductArt product={p} size={64} />
          </span>
          <span className="bcard__body">
            <span className="bcard__brand">{p.brand}</span>
            <span className="bcard__name">{p.name}</span>
            {job.pick?.shade && (
              <span className="bcard__shade">
                <span className="swatch" style={{ background: job.pick.shade.hex }} aria-hidden /> {job.pick.shade.name}
              </span>
            )}
            <span className="bcard__price">{job.status === "owned" ? "Already yours" : inr(job.pick!.price_inr)}</span>
          </span>
        </div>
      ) : (
        <p className="prose">{job.note}</p>
      )}
      {p && !p.inci_complete && <IncompleteTag />}
      {job.why.length > 0 && (
        <dl className="bcard__why">
          {job.why.map((w) => (
            <div key={w.key} className="bcard__whyrow">
              <dt>{w.label}</dt>
              <dd>{w.line}</dd>
            </div>
          ))}
        </dl>
      )}
      {job.status !== "none" && (
        <p className="bcard__how">
          <strong>{BASKET.howLabel}:</strong> {job.how_to_use}
        </p>
      )}
      {job.note && p && <p className="small muted">{job.note}</p>}
      {job.tried && job.tried.length > 0 && (
        <ul className="srclines">
          {job.tried.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}
      {job.look_for && <LookFor data={job.look_for} />}
      {job.also_fits.length > 0 && (
        <p className="small muted">
          {BASKET.alsoFits}:{" "}
          {job.also_fits
            .map((a) => `${a.name} (${inr(a.price_inr)}${a.patch_test_first ? `, ${BASKET.patchFirst}` : ""})`)
            .join(" · ")}
        </p>
      )}
    </li>
  );
}

function TryOnView({ basket, onBack }: { basket: BasketData; onBack: () => void }) {
  const t = basket.tryon;
  return (
    <div className="page page--wide">
      <NavBar back={null} left={<button className="textbtn" onClick={onBack}>‹ {BASKET.backToBasket}</button>} />
      {basket.source === "replay" && <p className="tag tag--prepared">{basket.demo_label ?? DEMO_DATA_TAG}</p>}
      <div className="tryonview">
        <div className="tryonview__info">
          <PageHead title={BASKET.tryonTitle} lede={BASKET.tryonLede} />
          {t.product && (
            <div className="tryonview__product">
              <ProductArt product={t.product} size={72} />
              <span className="tryonview__pname">
                <span className="bcard__brand">{t.product.brand}</span>
                <span className="bcard__name">{t.product.name}</span>
                {t.shade && (
                  <span className="bcard__shade">
                    <span className="swatch" style={{ background: t.shade.hex }} aria-hidden /> Shade {t.shade.name} ·{" "}
                    {t.undertone} undertone
                  </span>
                )}
              </span>
            </div>
          )}
          {t.status === "no_shade" && <Notice>{t.line}</Notice>}
          <div className="actions">
            <Btn onClick={onBack} wide>
              {BASKET.backToBasket}
            </Btn>
          </div>
        </div>
        {t.status !== "no_shade" && (
          <div className="tryon" role="group" aria-label={BASKET.tryonTitle}>
            {t.looks.map((lk) => (
              <figure key={lk.look} className="tryon__panel">
                {lk.image ? (
                  <img className="tryon__img" src={assetUrl(lk.image)} alt={`${lk.label} finish on your photo`} />
                ) : (
                  <div className="tryon__empty" style={{ background: t.shade?.hex }}>
                    <span className={`tryon__sheen tryon__sheen--${lk.look}`} aria-hidden />
                    <span className="tryon__wait">{t.line ?? BASKET.tryonPending}</span>
                  </div>
                )}
                <figcaption className="tryon__label">{lk.label}</figcaption>
              </figure>
            ))}
          </div>
        )}
      </div>
      <p className="foot small">{NOT_DIAGNOSIS} Try-on by YouCam AI Makeup Virtual Try-On.</p>
    </div>
  );
}

interface MyProfile {
  profile: ProfileData;
  chips: SavedChip[];
  records: SavedRecord[];
  shelf: string[];
  chipLabel: Record<string, string>;
  reactions: Record<string, string>;
}

/** "Update my profile too": this basket's finish, budget and beginner answers, the rest as saved. */
function profileFrom(p: ProfileData, a: Record<string, string>) {
  return {
    display_name: p.display_name,
    finish_goal: (["dewy", "natural", "matte"].includes(a.finish) ? a.finish : p.finish_goal) as ProfileData["finish_goal"],
    budget: (["under_700", "under_1000", "any"].includes(a.budget) ? a.budget : p.budget) as ProfileData["budget"],
    beginner: a.history === "new" ? true : a.history === "use" ? false : p.beginner,
  };
}

/** The saved history and shelf, each ticked: untick to leave it out of this basket only. A
 *  clinician-confirmed item can't be unticked; the server keeps it as a hard block either way. */
function ProfileItems({
  mine,
  use,
  setUse,
  showHistory,
}: {
  mine: MyProfile;
  use: ProfileUse;
  setUse: (u: ProfileUse) => void;
  showHistory: boolean;
}) {
  const { catalog } = useStore();
  const name = (id: string | null) => (id && catalog[id] ? `${catalog[id].brand} ${catalog[id].name}` : id ?? "");
  const toggle = (k: keyof ProfileUse, id: string, on: boolean) =>
    setUse({ ...use, [k]: on ? [...use[k], id] : use[k].filter((x) => x !== id) });
  const row = (k: keyof ProfileUse, id: string, label: string, locked: boolean) => (
    <li key={`${k}-${id}`}>
      <label className="checkrow">
        <input
          type="checkbox"
          checked={locked || use[k].includes(id)}
          disabled={locked}
          onChange={(e) => toggle(k, id, e.target.checked)}
        />
        <span>
          {label}
          <span className="small muted profileitems__from">
            {locked ? ACCOUNT.alwaysKept : ACCOUNT.fromProfile}
          </span>
        </span>
      </label>
    </li>
  );
  const history = showHistory && (mine.chips.length > 0 || mine.records.length > 0);
  if (!history && !mine.shelf.length) return <p className="small">{ACCOUNT.noHistory} <a href={href("/profile")}>{ACCOUNT.profile}</a></p>;
  return (
    <div className="profileitems">
      {history && (
        <>
          <p className="small">{ACCOUNT.profileItemsHelp}</p>
          <ul className="editlist">
            {mine.chips.map((c) =>
              row("chips", c.id, `${mine.chipLabel[c.chip] ?? c.chip}: ${mine.reactions[c.reaction] ?? c.reaction}`, c.clinician_confirmed)
            )}
            {mine.records.map((r) =>
              row("records", r.id, `${RECORD[r.type].short}: ${r.ingredient ?? name(r.product_id)}`, r.clinician_confirmed)
            )}
          </ul>
        </>
      )}
      {mine.shelf.length > 0 && (
        <>
          <h3 className="profile__sub">{ACCOUNT.youOwn}</h3>
          <ul className="editlist">{mine.shelf.map((id) => row("shelf", id, name(id), false))}</ul>
        </>
      )}
    </div>
  );
}
