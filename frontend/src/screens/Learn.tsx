import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, livePasscode, setLivePasscode, type VerdictCode } from "../api";
import { DELETE_SCANS, deletedSummary, NOT_DIAGNOSIS, PRIVACY, REACTION_RULE, VERDICT } from "../copy";
import { Icon } from "../components/Icon";
import { Btn, NavBar, Notice, PageHead, Section } from "../components/ui";
import { useStore } from "../store";

// Applied top-down; the first that fits wins. "No baseline yet" is the state before any verdict is possible.
const LEVELS: { code: VerdictCode; when: string }[] = [
  { code: "stop_reaction", when: "You reported a stop sign such as itching or burning. It overrides everything below, and stays until you mark it resolved." },
  { code: "cant_tell_not_comparable", when: "The check-in photos were taken in different light, at a different distance or angle, on another camera or at another time of day." },
  { code: "cant_tell_several_changes", when: "More than one new leave-on product started during the trial, so no single one can be credited or blamed." },
  { code: "no_detectable_change", when: "Your check-in scores sit inside the range your face moves on its own." },
  { code: "moved_beyond_noise", when: "The check-in range and your baseline range don't overlap, and the photos are comparable. Shown with its direction, never as proof the product did it." },
];

export default function Learn({ section }: { section?: string | null }) {
  const { meta, health, refresh } = useStore();
  const dataRef = useRef<HTMLElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "info" | "stop"; text: string } | null>(null);
  const [code, setCode] = useState(livePasscode());

  const saveCode = async (e: FormEvent) => {
    e.preventDefault();
    setLivePasscode(code);
    await refresh();
  };

  useEffect(() => {
    if (section === "data") dataRef.current?.scrollIntoView({ block: "start" });
  }, [section]);

  const del = async () => {
    if (!confirm(DELETE_SCANS.confirm)) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.deleteCaptures();
      await refresh();
      setMsg({ tone: r.youcam?.failed ? "stop" : "info", text: deletedSummary(r) });
    } catch (e) {
      setMsg({ tone: "stop", text: e instanceof ApiError ? e.message : "Couldn't delete. Try again." });
    } finally {
      setBusy(false);
    }
  };

  const tol = meta?.tolerances;

  return (
    <div className="page">
      <NavBar />
      <PageHead title="How derm//os decides" lede="Three ideas, in plain words. YouCam measures your skin; fixed, tested rules decide what the numbers mean." />

      <Section label="Your noise floor">
        <p className="prose">
          Skin scores move a little between two photos even when nothing has changed. So your baseline is three photos, not one.
          For each concern, the lowest and highest of those scores make your own range: your noise floor.
        </p>
        <p className="prose">
          At each check-in you take two photos, which give a second range. A change only counts if the two ranges don't overlap.
          Small ups and downs inside your range are normal.
        </p>
      </Section>

      <Section label="The comparability gate">
        <p className="prose">
          Every photo carries a fingerprint of how it was taken: light level and colour, how much of the frame your face fills,
          head angle, camera and time of day. A check-in is only compared with your baseline when these match.
        </p>
        {tol && (
          <ul className="bullets">
            <li>Brightness within {tol.luminance} on a 0 to 1 scale, light colour within {Math.round(tol.red_blue_ratio * 100)}%.</li>
            <li>Face size within {Math.round(tol.face_ratio * 100)}% of the frame width.</li>
            <li>Head angle within {tol.angle}° each way.</li>
            <li>Same camera, and within {tol.hour} hours of the same time of day, when the photo records them.</li>
          </ul>
        )}
        <p className="prose">When photos don't match, derm//os says “can't tell” and shows how to retake, instead of reporting a trend.</p>
      </Section>

      <Section label="Five verdict levels">
        <ol className="levels">
          {LEVELS.map((l) => (
            <li key={l.code} className={`level level--${VERDICT[l.code].tone}`}>
              <span className="level__name">{VERDICT[l.code].kicker}</span>
              <span className="level__when">{l.when}</span>
              {meta?.verdict_text?.[l.code] && <span className="level__says">It says: “{meta.verdict_text[l.code]}”</span>}
            </li>
          ))}
        </ol>
        <p className="prose">
          Before there are at least 2 baseline and 2 check-in scans, the answer is simply “{VERDICT.cant_tell_no_baseline.kicker}”.
        </p>
      </Section>

      <Section label="Two rules that never bend">
        <ul className="bullets">
          <li>Symptoms outrank scores. {REACTION_RULE}</li>
          <li>The strongest thing derm//os says is “changed during this trial”, never “caused by”. Seasons, sleep and cycles move skin too.</li>
          <li>A product with an incomplete ingredient list is “unknown”, never a pass. With no ingredient recorded to avoid, every product shows “nothing to check against yet”, also never a pass.</li>
        </ul>
      </Section>

      <Section label="Where the AI fits">
        <p className="prose">
          The AI only extracts and words things. Rules decide. It can turn your own description into suggested history records,
          which you confirm one by one, and it can put a result into plain sentences. A checker rejects any sentence that claims a
          cause, names a condition, mentions a product or number that isn't in your record, or sounds surer than the verdict; then
          you see the fixed wording instead. Verdicts and exclusion checks never go through the AI
          {health?.llm === false ? ", and on this server it is switched off" : ""}.
        </p>
      </Section>

      <section className="section" ref={dataRef} id="your-data" aria-labelledby="your-data-h">
        <div className="section__head">
          <h2 className="section__label" id="your-data-h">
            Your photos and scans
          </h2>
        </div>
        <div className="privacy">
          <Icon name="lock" size={20} />
          <p>{health?.demo_mode ? PRIVACY.demo : PRIVACY.live}</p>
        </div>
        <p className="small muted">{DELETE_SCANS.short}</p>
        {msg && <Notice tone={msg.tone === "stop" ? "stop" : "info"}>{msg.text}</Notice>}
        <Btn kind="danger" onClick={del} disabled={busy} wide icon="trash">
          {busy ? "Deleting…" : "Delete my saved scans"}
        </Btn>
      </section>

      {health?.live_scans === "passcode" && (
        <Section label="Live scans">
          <p className="prose">
            This server replays prepared scans unless you enter the live-scan passcode. With it, your photos go to YouCam and use
            real analysis units.
          </p>
          <form className="demobox" onSubmit={saveCode}>
            <label className="field">
              <span>Live-scan passcode (saved on this device only)</span>
              <input type="password" autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} />
            </label>
            <Btn kind="quiet" type="submit">
              {code ? "Save passcode" : "Clear passcode"}
            </Btn>
            {health.passcode === "ok" && <Notice tone="info">Live scans are on for this device.</Notice>}
            {health.passcode === "wrong" && <Notice tone="stop">That passcode isn't right. Scans will be refused until you fix or clear it.</Notice>}
          </form>
        </Section>
      )}

      <p className="foot small">
        {NOT_DIAGNOSIS} Skin measurements by YouCam AI Skin Analysis. All products shown are fictional.
        {health?.rules?.length ? ` Rule sets ${health.rules.join(", ")}.` : ""}
      </p>
    </div>
  );
}
