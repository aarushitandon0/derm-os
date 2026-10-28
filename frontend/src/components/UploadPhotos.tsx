import { useState, type ReactNode } from "react";
import { api, ApiError, type PrecheckResult, type Place, type UploadScanResult } from "../api";
import { UPLOAD } from "../copy";
import { Icon } from "./Icon";
import { Btn, Notice, PageHead } from "./ui";

type Phase = "baseline" | "checkin";

/** A simulated state for screenshots (DEV only, no photos): see capture/preview.ts. */
export interface UploadSimulation {
  count: number;
  result: PrecheckResult | null;
  done?: UploadScanResult | null;
}

/**
 * Upload photos instead of taking them. The free precheck runs first (no YouCam call, nothing
 * stored) and the Scan button only appears when it passes. The server runs every check again on
 * Scan, so this screen is a convenience, not the gate.
 */
export function UploadPhotos({
  phase,
  trialId,
  demo,
  fixtureSet,
  place,
  placePicker,
  onDone,
  onCamera,
  simulated,
}: {
  phase: Phase;
  trialId?: string;
  demo: boolean;
  fixtureSet: string | null;
  place: Place | null;
  placePicker?: ReactNode;
  onDone: () => void;
  onCamera: () => void;
  simulated?: UploadSimulation | null;
}) {
  const total = phase === "baseline" ? 3 : 2;
  const [files, setFiles] = useState<File[]>([]);
  const [result, setResult] = useState<PrecheckResult | null>(simulated?.result ?? null);
  const [busy, setBusy] = useState<"checking" | "scanning" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sameSitting, setSameSitting] = useState<boolean | null>(null);
  const [done, setDone] = useState<UploadScanResult | null>(simulated?.done ?? null);
  const count = simulated ? simulated.count : files.length;

  const input = (fs: File[], ss: boolean | null) => ({
    files: fs,
    phase,
    trialId,
    sameSitting: ss,
    persona: demo ? "riya" : undefined,
    fixtureSet: demo && fixtureSet ? fixtureSet : null,
    place: phase === "baseline" ? place : null,
  });

  const check = async (fs: File[], ss: boolean | null) => {
    setBusy("checking");
    setErr(null);
    setResult(null);
    try {
      setResult(await api.precheck(input(fs, ss)));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : UPLOAD.checkFailed);
    } finally {
      setBusy(null);
    }
  };

  const pick = (list: FileList | null) => {
    const fs = Array.from(list ?? []);
    setSameSitting(null);
    setResult(null);
    setDone(null);
    if (!fs.length) return;
    if (fs.length !== total) {
      setFiles([]);
      setErr(UPLOAD.wrongCount(total, fs.length));
      return;
    }
    setFiles(fs);
    void check(fs, null);
  };

  const answer = (yes: boolean) => {
    setSameSitting(yes);
    void check(files, yes);
  };

  const scan = async () => {
    if (simulated) return;
    setBusy("scanning");
    setErr(null);
    try {
      setDone(await api.uploadScan(input(files, sameSitting)));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : UPLOAD.scanFailed);
    } finally {
      setBusy(null);
    }
  };

  // ------------------------------------------------------------ after the scan
  if (done) {
    const replay = done.captures.some((c) => c.source === "replay");
    return (
      <>
        <PageHead
          title={phase === "baseline" ? "First photos saved" : "Check-in saved"}
          lede={UPLOAD.saved(done.captures.length, phase)}
        />
        <ul className="uplist" aria-label="Saved photos">
          {done.captures.map((c, i) => (
            <li key={c.id} className="uplist__row">
              <span className="uplist__num">Photo {i + 1}</span>
              <span className="tag tag--upload">
                <Icon name="share" size={12} /> Uploaded photo
              </span>
              {replay && <span className="tag tag--prepared">Prepared demo data</span>}
            </li>
          ))}
        </ul>
        {done.captures[0]?.baseline_timing === "user-confirmed" && <p className="small muted">{UPLOAD.userConfirmed}</p>}
        {done.notice && <Notice tone="warn">{done.notice}</Notice>}
        <div className="flow__foot">
          <Btn onClick={onDone} wide>
            {phase === "baseline" ? "See your trial" : "See your results"}
          </Btn>
        </div>
      </>
    );
  }

  // ------------------------------------------------------------ choose and check
  const passed = !!result?.ok;
  return (
    <>
      <PageHead title={phase === "baseline" ? "Upload your first photos" : "Upload your check-in photos"} lede={UPLOAD.lede[phase]} />

      <label className={`btn btn--${passed ? "ghost" : "primary"} btn--wide filebtn${busy ? " is-disabled" : ""}`}>
        <input
          type="file"
          className="filebtn__input"
          accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif"
          multiple
          disabled={!!busy}
          onChange={(e) => {
            pick(e.target.files);
            e.target.value = ""; // choosing the same photos again still runs the checks
          }}
        />
        <span>{count ? UPLOAD.chooseAgain : UPLOAD.choose(total)}</span>
      </label>
      <p className="formhelp">{UPLOAD.unedited}</p>
      {demo && <p className="small muted">{UPLOAD.demo}</p>}

      {busy === "checking" && (
        <p className="livehint" role="status">
          {UPLOAD.checking(count)}
        </p>
      )}
      {err && <Notice tone="stop">{err}</Notice>}

      {result && (
        <ul className="uplist" aria-label="Photo checks">
          {result.photos.map((p) => (
            <li key={p.index} className={`uplist__row${p.ok ? "" : " is-bad"}`}>
              <span className="uplist__mark" aria-hidden>
                <Icon name={p.ok ? "check" : "close"} size={14} />
              </span>
              <span className="uplist__num">Photo {p.index}</span>
              <span className="uplist__sub">
                {p.ok ? UPLOAD.photoLine(p.hour ?? null, p.device ?? "not recorded") : UPLOAD.photoBad}
              </span>
              {p.warning && <span className="uplist__warn">{p.warning}</span>}
            </li>
          ))}
        </ul>
      )}

      {result && result.needs_confirmation && (
        <fieldset className="placepick">
          <legend className="placepick__q">{result.message}</legend>
          <p className="formhelp">{UPLOAD.whyAsk}</p>
          <div className="chips">
            <button type="button" className="symchip" onClick={() => answer(true)} disabled={!!busy}>
              Yes, one sitting
            </button>
            <button type="button" className="symchip" onClick={() => answer(false)} disabled={!!busy}>
              No
            </button>
          </div>
        </fieldset>
      )}
      {result && !result.ok && !result.needs_confirmation && result.message && <Notice tone="stop">{result.message}</Notice>}

      {passed && (
        <>
          <Notice tone="info">{UPLOAD.passed}</Notice>
          {phase === "baseline" && placePicker}
          <div className="flow__foot">
            <Btn onClick={scan} disabled={!!busy} wide>
              {busy === "scanning" ? UPLOAD.scanning : UPLOAD.scan(count)}
            </Btn>
          </div>
        </>
      )}

      <button type="button" className="textbtn textbtn--center" onClick={onCamera}>
        Use the camera instead
      </button>
    </>
  );
}
