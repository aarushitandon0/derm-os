import { useEffect, useState, type FormEvent } from "react";
import { useAccount } from "../account";
import { isLoggedOut, isWaking, meApi } from "../api";
import { ACCOUNT } from "../accountCopy";
import { answerImport, IMPORT_QUESTION, shouldAsk, summary, type DeviceData } from "../deviceImport";
import { clearDevice, deviceData, importAskedKey, readLocal, writeLocal } from "../local";
import { href } from "../router";
import { Btn, Notice } from "./ui";

/** A plain sentence for any failed account call. A sleeping server is never read as "logged out". */
export function accountError(e: unknown): string {
  if (isWaking(e)) return ACCOUNT.waking;
  if (isLoggedOut(e)) return ACCOUNT.loggedOut;
  return (e as Error).message;
}

/** Header control: "Log in", or "Profile" once logged in. Hidden when accounts aren't set up. */
export function AccountButton() {
  const a = useAccount();
  if (!a.enabled || !a.ready) return null;
  return (
    <a className="btn btn--quiet acctbtn" href={href(a.session ? "/profile" : "/login")}>
      <span>{a.session ? ACCOUNT.profile : ACCOUNT.logIn}</span>
    </a>
  );
}

type Mode = "login" | "signup" | "forgot";

/** Email + password: log in, sign up, or a reset link. `onDone` runs once a session exists. */
export function AuthForm({ onDone, intro }: { onDone?: () => void; intro?: string }) {
  const a = useAccount();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setInfo(null);
    setBusy(true);
    try {
      if (mode === "forgot") {
        await a.resetPassword(email.trim());
        setInfo(ACCOUNT.resetSent);
      } else if (mode === "signup") {
        const r = await a.signUp(email.trim(), password);
        if (r.confirm) setInfo(ACCOUNT.confirmSent);
        else onDone?.();
      } else {
        await a.signIn(email.trim(), password);
        onDone?.();
      }
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="authform" onSubmit={submit} noValidate>
      {intro && <p className="formhelp">{intro}</p>}
      <div className="authform__modes" role="tablist" aria-label={ACCOUNT.modesLabel}>
        {(["login", "signup"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            className={`authform__mode${mode === m ? " is-on" : ""}`}
            onClick={() => setMode(m)}
          >
            {m === "login" ? ACCOUNT.logIn : ACCOUNT.signUp}
          </button>
        ))}
      </div>
      <label className="field">
        <span>{ACCOUNT.email}</span>
        <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      {mode !== "forgot" && (
        <label className="field">
          <span>{ACCOUNT.password}</span>
          <input
            type="password"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
      )}
      {err && <Notice tone="stop">{err}</Notice>}
      {info && <Notice>{info}</Notice>}
      <Btn type="submit" wide disabled={busy || !email.trim() || (mode !== "forgot" && password.length < 8)}>
        {busy ? ACCOUNT.wait : mode === "login" ? ACCOUNT.logIn : mode === "signup" ? ACCOUNT.createAccount : ACCOUNT.sendReset}
      </Btn>
      <button type="button" className="textbtn textbtn--center" onClick={() => setMode(mode === "forgot" ? "login" : "forgot")}>
        {mode === "forgot" ? ACCOUNT.backToLogin : ACCOUNT.forgot}
      </button>
      <p className="small muted">{ACCOUNT.photoLine}</p>
    </form>
  );
}

/** After the reset-password link: choose a new password. */
export function NewPassword() {
  const a = useAccount();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  if (!a.recovering && !done) return null;
  if (done) return <Notice>{ACCOUNT.passwordChanged}</Notice>;
  return (
    <form
      className="authform"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await a.updatePassword(pw);
          setDone(true);
        } catch (e2) {
          setErr((e2 as Error).message);
        }
      }}
    >
      <label className="field">
        <span>{ACCOUNT.newPassword}</span>
        <input type="password" autoComplete="new-password" minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} />
      </label>
      {err && <Notice tone="stop">{err}</Notice>}
      <Btn type="submit" wide disabled={pw.length < 8}>
        {ACCOUNT.setPassword}
      </Btn>
    </form>
  );
}

/** On the basket. A guest logs in right here, and the basket on screen is the one saved. */
export function SaveBasketCard({ basketId, demo }: { basketId: string; demo: boolean }) {
  const a = useAccount();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [waking, setWaking] = useState(false);

  const save = async () => {
    setErr(null);
    setWaking(false);
    setBusy(true);
    try {
      const t = await a.token();
      if (!t) {
        setOpen(true);
        return;
      }
      await meApi.saveBasket(t, basketId);
      setSaved(true);
      setOpen(false);
    } catch (e) {
      setErr(accountError(e));
      setWaking(isWaking(e));
    } finally {
      setBusy(false);
      setPending(false);
    }
  };

  // Logged in from the form below: save the basket that was on screen.
  useEffect(() => {
    if (pending && a.session) void save();
  }, [pending, a.session]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!a.enabled || !a.ready) return null;
  if (saved)
    return (
      <div className="savecard" role="status">
        <p className="savecard__done">{ACCOUNT.saved}</p>
        <Btn to="/profile" kind="ghost" wide>
          {ACCOUNT.openProfile}
        </Btn>
      </div>
    );
  return (
    <div className="savecard">
      {demo && <p className="small muted">{ACCOUNT.demoSaveNote}</p>}
      {!open && (
        <Btn onClick={save} kind="ghost" wide disabled={busy}>
          {busy ? ACCOUNT.wait : ACCOUNT.saveBasket}
        </Btn>
      )}
      {open && !a.session && <AuthForm intro={ACCOUNT.saveIntro} onDone={() => setPending(true)} />}
      {err && (
        <Notice tone={waking ? "warn" : "stop"}>
          {err}{" "}
          <button type="button" className="textbtn" onClick={save}>
            {ACCOUNT.retry}
          </button>
        </Notice>
      )}
    </div>
  );
}

/** Once per account on this device, only if this device has history the person entered. */
export function ImportPrompt() {
  const a = useAccount();
  const [data, setData] = useState<DeviceData | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const uid = a.userId;

  useEffect(() => {
    if (!uid) return setData(null);
    const d = deviceData();
    setData(shouldAsk(d, readLocal<boolean>(importAskedKey(uid), false)) ? d : null);
  }, [uid]);

  if (!uid || (!data && !msg)) return null;
  if (msg)
    return (
      <div className="importprompt" role="status">
        <p>{msg}</p>
        <button type="button" className="textbtn" onClick={() => setMsg(null)}>
          {ACCOUNT.close}
        </button>
      </div>
    );

  const answer = async (ans: "yes" | "no") => {
    setBusy(true);
    try {
      const out = await answerImport(ans, data!, async (d) => {
        const t = await a.token();
        if (!t) throw new Error(ACCOUNT.loggedOut);
        return meApi.importDevice(t, d);
      });
      writeLocal(importAskedKey(uid), true);
      if (out === "imported") {
        clearDevice();
        setMsg(ACCOUNT.imported);
      }
      setData(null);
    } catch (e) {
      setMsg(accountError(e)); // not marked as asked: it asks again next time
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="importprompt" role="dialog" aria-labelledby="import-q">
      <p id="import-q" className="importprompt__q">
        {IMPORT_QUESTION}
      </p>
      <p className="small muted">{summary(data!)}</p>
      <div className="importprompt__row">
        <Btn onClick={() => answer("yes")} disabled={busy}>
          {ACCOUNT.yesAdd}
        </Btn>
        <Btn onClick={() => answer("no")} kind="ghost" disabled={busy}>
          {ACCOUNT.noKeep}
        </Btn>
      </div>
    </div>
  );
}
