import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Capture as Cap, type Comparability, type ConditionField } from "../api";
import { checklist, deviceLabel, faceMetrics, lightMetrics, loadLandmarker, type CheckItem, type FaceMetrics } from "../capture/faceGuide";
import { ANALYSIS_STEPS, CONDITION, CONDITION_ROWS, CONDITION_STATE, PRIVACY } from "../copy";
import { Icon, type IconName } from "../components/Icon";
import { Btn, NavBar, Notice, PageHead } from "../components/ui";
import { go, href } from "../router";
import { useStore } from "../store";

type Phase = "baseline" | "checkin";
type Stage = "starting" | "live" | "analysing" | "quality" | "error";
type StepState = "pending" | "active" | "done";
type StepKey = "upload" | "analyse" | "calibrate" | "prepare";
type Steps = Record<StepKey, StepState> & { uploadFraction: number };

const SHOTS: Record<Phase, number> = { baseline: 3, checkin: 2 };
const HOLD_MS = 600;
// After the last real step finishes, keep the finished list on screen briefly so it can be read.
const SETTLE_MS = 450;
const FRESH: Steps = { upload: "pending", analyse: "pending", calibrate: "pending", prepare: "pending", uploadFraction: 0 };

interface Shot {
  capture: Cap;
  comparability: Comparability | null;
  liveChecked: boolean; // the live MediaPipe checks passed before the shutter (not for file uploads)
}

export default function Capture({ phase, trialId }: { phase: Phase; trialId?: string }) {
  const { health, refresh } = useStore();
  const demo = !!health?.demo_mode;
  const total = SHOTS[phase];
  const exitTo = trialId ? `/trial/${trialId}` : "/";

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const metricsRef = useRef<FaceMetrics | null>(null);
  const passSince = useRef<number | null>(null);
  const alive = useRef(true);

  const [stage, setStage] = useState<Stage>("starting");
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<{ w: number; h: number } | null>(null);
  const [checks, setChecks] = useState<CheckItem[]>(checklist(null, null));
  const [ready, setReady] = useState(false);
  const [guideState, setGuideState] = useState<"loading" | "ok" | "failed">("loading");
  const [done, setDone] = useState(0);
  const [steps, setSteps] = useState<Steps>(FRESH);
  const [shot, setShot] = useState<Shot | null>(null);
  const [restarted, setRestarted] = useState(false);
  const [fixtureSet, setFixtureSet] = useState<string>("");

  const short = res ? Math.min(res.w, res.h) : 0;
  const tooLow = !!res && short < 480;

  useEffect(
    () => () => {
      alive.current = false;
    },
    []
  );

  // ------------------------------------------------------------ camera
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("This browser can't open the camera. Use a phone browser over https (or localhost).");
        setStage("error");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: "user", width: { ideal: 4096 }, height: { ideal: 4096 } },
        });
        if (cancelled) return stream.getTracks().forEach((t) => t.stop());
        streamRef.current = stream;
        const v = videoRef.current!;
        v.srcObject = stream;
        await v.play();
        setRes({ w: v.videoWidth, h: v.videoHeight });
        setStage("live");
      } catch (e) {
        setError(
          (e as DOMException)?.name === "NotAllowedError"
            ? "Camera permission was declined. Allow camera access in your browser settings to scan."
            : "Couldn't open the camera."
        );
        setStage("error");
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // ------------------------------------------------------------ live checks
  useEffect(() => {
    if (stage !== "live") return;
    let raf = 0;
    let last = 0;
    let stop = false;
    let lm: Awaited<ReturnType<typeof loadLandmarker>> | null = null;
    loadLandmarker()
      .then((l) => {
        lm = l;
        setGuideState("ok");
      })
      .catch(() => setGuideState("failed"));

    const tick = (t: number) => {
      if (stop) return;
      raf = requestAnimationFrame(tick);
      const v = videoRef.current;
      if (!v || !lm || v.readyState < 2 || t - last < 120) return;
      last = t;
      const f = faceMetrics(lm.detectForVideo(v, performance.now()));
      const l = lightMetrics(v, f.box);
      metricsRef.current = f;
      const items = checklist(f, l);
      setChecks(items);
      const allOk = items.every((i) => i.ok);
      if (allOk) {
        passSince.current ??= t;
        setReady(t - passSince.current >= HOLD_MS);
      } else {
        passSince.current = null;
        setReady(false);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => {
      stop = true;
      cancelAnimationFrame(raf);
    };
  }, [stage]);

  // ------------------------------------------------------------ shutter → analysing → quality
  const upload = useCallback(
    async (blob: Blob, m: FaceMetrics | null, liveChecked: boolean, taken?: { hour: number; device: string | null }) => {
      setStage("analysing");
      setError(null);
      setSteps({ ...FRESH, upload: "active" });
      try {
        const r = await api.scan(
          {
            image: blob,
            phase,
            trialId,
            faceRatio: m?.faceRatio ?? null,
            yaw: m?.yaw ?? null,
            pitch: m?.pitch ?? null,
            roll: m?.roll ?? null,
            persona: demo ? "riya" : undefined,
            fixtureSet: demo && fixtureSet ? fixtureSet : null,
            clientHour: taken?.hour ?? null,
            clientDevice: taken?.device ?? null,
          },
          (fraction, uploaded) =>
            alive.current &&
            setSteps((s) =>
              uploaded
                ? { ...s, upload: "done", uploadFraction: 1, analyse: s.analyse === "done" ? "done" : "active" }
                : { ...s, uploadFraction: fraction }
            )
        );
        if (!alive.current) return;
        // The response carries the analysis and the baseline comparison together.
        setSteps((s) => ({ ...s, upload: "done", uploadFraction: 1, analyse: "done", calibrate: "done", prepare: "active" }));
        const n = done + 1;
        if (n >= total) await refresh();
        if (!alive.current) return;
        setSteps((s) => ({ ...s, prepare: "done" }));
        setDone(n);
        setShot({ capture: r.capture, comparability: r.comparability, liveChecked });
        await new Promise((ok) => setTimeout(ok, SETTLE_MS));
        if (alive.current) setStage("quality");
      } catch (e) {
        if (!alive.current) return;
        setError(e instanceof ApiError ? e.message : "The scan didn't go through. Try again.");
        setStage("live");
      }
    },
    [phase, trialId, demo, fixtureSet, done, total, refresh]
  );

  const shoot = () => {
    const v = videoRef.current;
    if (!v) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth; // full camera resolution, not the preview size
    c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    const m = metricsRef.current;
    // The canvas JPEG has no EXIF, so record the local hour and a coarse camera label now.
    const taken = { hour: new Date().getHours(), device: deviceLabel(streamRef.current, c.width, c.height) };
    c.toBlob((b) => b && upload(b, m, true, taken), "image/jpeg", 0.92);
  };

  const fromFile = (file: File | undefined) => file && upload(file, null, false);

  const backToLive = () => {
    passSince.current = null;
    setReady(false);
    setShot(null);
    setSteps(FRESH);
    setStage("live");
  };

  const finish = () => {
    if (phase === "baseline") go(trialId ? `/trial/${trialId}` : "/");
    else go(trialId ? `/results/${trialId}` : "/");
  };

  // A check-in pair is compared as a pair, so a retake starts the pair again.
  const retake = () => {
    setDone(0);
    setRestarted(true);
    backToLive();
  };

  const shutterEnabled = stage === "live" && ready && !tooLow && guideState === "ok";
  const counter = `${Math.min(stage === "quality" ? done : done + 1, total)} of ${total}`;
  const nav = (
    <NavBar
      left={
        <a className="navtext" href={href(exitTo)}>
          Cancel
        </a>
      }
      center={<span className="navcount">{counter}</span>}
    />
  );

  // ------------------------------------------------------------ analysing
  const analysingView = stage === "analysing" && (
      <>
        <PageHead
          title="Analysing your skin"
          lede={demo ? "Demo mode: prepared scores, measured against your real photo's light and framing." : "Waiting for YouCam's analysis."}
        />
        <Analysing steps={steps} phase={phase} />
        <div className="privacy">
          <Icon name="lock" size={20} />
          <p>
            {demo ? PRIVACY.demo : PRIVACY.live}{" "}
            <a href={href("/learn?section=data")}>Manage saved scans</a>
          </p>
        </div>
      </>
    );

  // ------------------------------------------------------------ quality
  let qualityView: JSX.Element | null = null;
  if (stage === "quality" && shot) {
    const c = shot.comparability;
    const rows = conditionRows(shot);
    const failed = rows.some((r) => r.state === "fail");
    const last = done >= total;
    const lede =
      phase === "checkin" && c
        ? c.comparable
          ? "Looks good. This photo is comparable to your baseline."
          : "This photo doesn't match your baseline conditions, so it won't be compared."
        : phase === "checkin"
        ? "Saved. There's no baseline yet, so there's nothing to compare it with."
        : `Baseline photo ${done} of ${total} saved. These are the conditions to match at each check-in.`;
    qualityView = (
      <>
        <PageHead title="Check capture quality" lede={lede} />
        <ul className="conditions" aria-label="Capture conditions">
          {rows.map((r) => (
            <li key={r.field} className={`condition condition--${r.state}`}>
              <span className="condition__icon">
                <Icon name={ROW_ICON[r.field]} />
              </span>
              <span className="condition__body">
                <span className="condition__label">{CONDITION[r.field].label}</span>
                <span className="condition__sub">{r.sub}</span>
                {r.fix && <span className="condition__fix">{r.fix}</span>}
              </span>
              <span className="condition__mark" aria-label={r.state === "pass" ? "Passed" : r.state === "fail" ? "Doesn't match" : "Not checked"}>
                {r.state === "pass" ? <Icon name="check" size={14} /> : r.state === "fail" ? <Icon name="close" size={14} /> : null}
              </span>
            </li>
          ))}
        </ul>
        {shot.capture.source === "replay" && (
          <p className="small muted">Scores are prepared data; the conditions above were measured from your real photo.</p>
        )}
        <div className="flow__foot">
          {failed ? (
            <>
              <Btn onClick={retake} wide>
                Retake
              </Btn>
              <p className="small muted center">A retake starts this check-in's pair of photos again.</p>
              <button type="button" className="textbtn textbtn--center" onClick={last ? finish : backToLive}>
                {last ? "Continue anyway" : "Keep it and take the next photo"}
              </button>
            </>
          ) : (
            <Btn onClick={last ? finish : backToLive} wide>
              {last ? (phase === "baseline" ? "See your trial" : "See your results") : "Continue"}
            </Btn>
          )}
        </div>
      </>
    );
  }

  // ------------------------------------------------------------ live camera
  // The camera stays mounted through every stage so the stream survives between photos.
  const showCamera = stage === "starting" || stage === "live" || stage === "error";
  return (
    <div className={`page page--flow${showCamera ? " page--capture" : ""}`}>
      {nav}
      {analysingView}
      {qualityView}
      <div hidden={!showCamera}>
      <PageHead
        title={phase === "baseline" ? "Take your baseline" : "Take your check-in"}
        lede={
          phase === "baseline"
            ? "We'll take 3 quick photos to measure your personal noise floor."
            : "Two photos in the same spot and light as your baseline."
        }
      />
      {restarted && phase === "checkin" && stage === "live" && (
        <Notice>Retaking both check-in photos, so the pair matches your baseline.</Notice>
      )}

      <div className={`viewfinder${ready ? " viewfinder--ready" : ""}`}>
        <video ref={videoRef} playsInline muted className="viewfinder__video" />
        <svg className="viewfinder__guide" viewBox="0 0 300 400" preserveAspectRatio="none" aria-hidden>
          <ellipse cx="150" cy="190" rx="92" ry="128" />
          <line x1="150" y1="40" x2="150" y2="350" />
          <line x1="40" y1="190" x2="260" y2="190" />
        </svg>
        {stage === "starting" && <p className="viewfinder__msg">Opening camera…</p>}
        {stage === "error" && <p className="viewfinder__msg">Camera unavailable</p>}
        {res && (
          <span className="viewfinder__res">
            {res.w}×{res.h}
          </span>
        )}
      </div>

      <ul className="livechecks" aria-label="Live checks">
        {checks.map((c) => (
          <li key={c.key} className={`livecheck${c.ok ? " is-ok" : ""}`} title={c.label}>
            <span className="livecheck__dot" aria-hidden>
              {c.ok && <Icon name="check" size={12} />}
            </span>
            <span className="livecheck__label">{SHORT[c.key] ?? c.label}</span>
            <span className="sr-only">{c.ok ? "passed" : "not yet"}</span>
          </li>
        ))}
      </ul>
      <p className="livehint" aria-live="polite">
        {guideState === "loading" ? "Loading the face guide…" : (checks.find((c) => !c.ok) ?? checks[0]).hint}
      </p>

      {tooLow && (
        <Notice tone="stop">
          This camera gives {short}px on the short side. YouCam needs at least 480px (SD) and 1080px for HD. Open derm//os
          on your phone instead.
        </Notice>
      )}
      {res && !tooLow && short < 1080 && (
        <Notice tone="warn">{short}px short side: fine for SD scans. HD analysis would need 1080px.</Notice>
      )}
      {guideState === "failed" && (
        <Notice tone="warn">The face guide couldn't load (it needs a connection the first time). Reload to try again.</Notice>
      )}
      {error && <Notice tone="stop">{error}</Notice>}

      <div className="shutterwrap">
        <button className="shutter" disabled={!shutterEnabled} onClick={shoot} aria-label="Take photo">
          <span className="shutter__ring" />
        </button>
        <p className="shutter__label">{shutterEnabled ? "Hold still and tap." : "The shutter unlocks when all three checks pass."}</p>
      </div>

      {demo && (
        <div className="demobox">
          <p>
            <strong>Demo mode.</strong> Scores replay prepared data. Light, face size and angle are still measured from your
            real photo.
          </p>
          {phase === "checkin" && (
            <label className="field">
              <span>Prepared scores</span>
              <select value={fixtureSet} onChange={(e) => setFixtureSet(e.target.value)}>
                <option value="">Matched check-in</option>
                <option value="lamp">Warm-lamp check-in</option>
              </select>
            </label>
          )}
          <label className="filepick">
            <span>Or use a photo (demo only, skips the live checks)</span>
            <input
              type="file"
              accept="image/jpeg,image/png"
              onChange={(e) => {
                fromFile(e.target.files?.[0]);
                e.target.value = ""; // so choosing the same file again still triggers a scan
              }}
            />
          </label>
        </div>
      )}
      </div>
    </div>
  );
}

const SHORT: Record<string, string> = { size: "Face size", pose: "Angle", light: "Light" };

const ROW_ICON: Record<ConditionField, IconName> = {
  lighting: "sun",
  face_size: "frame",
  head_pose: "pose",
  time_of_day: "clock",
  device: "phone",
  mode: "layers",
};

type Row = { field: ConditionField; state: "pass" | "fail" | "neutral"; sub: string; fix?: string };

/** Rows from the backend's comparability result (check-ins) or the recorded fingerprint (baseline). */
function conditionRows(shot: Shot): Row[] {
  const c = shot.comparability;
  const fp = shot.capture.fingerprint;
  const fields: ConditionField[] = [...CONDITION_ROWS];
  if (c?.failed?.some((f) => f.field === "mode")) fields.push("mode");

  const detail: Partial<Record<ConditionField, string | null>> = {
    lighting: typeof fp.luminance === "number" ? `brightness ${fp.luminance.toFixed(2)}` : null,
    face_size: typeof fp.face_ratio === "number" ? `${Math.round(fp.face_ratio * 100)}% of frame width` : null,
    head_pose: typeof fp.yaw === "number" ? `turned ${Math.abs(fp.yaw).toFixed(0)}°` : null,
    time_of_day: typeof fp.captured_hour === "number" ? `${String(fp.captured_hour).padStart(2, "0")}:00` : null,
    device: fp.device || null,
  };
  const withDetail = (base: string, f: ConditionField) => (detail[f] ? `${base} · ${detail[f]}` : base);

  return fields.map((f) => {
    if (c) {
      const miss = (c.failed ?? []).filter((x) => x.field === f);
      if (miss.length)
        return { field: f, state: "fail", sub: miss.map((m) => m.reason).join(" "), fix: [...new Set(miss.map((m) => m.fix))].join(" ") };
      const skipped = (c.not_compared ?? []).find((x) => x.field === f);
      if (skipped) return { field: f, state: "neutral", sub: `${CONDITION_STATE.notCompared}: ${skipped.reason}` };
      if (c.checked?.includes(f)) return { field: f, state: "pass", sub: CONDITION_STATE.match };
      return { field: f, state: "neutral", sub: CONDITION_STATE.notRecorded };
    }
    const live = shot.liveChecked && (f === "lighting" || f === "face_size" || f === "head_pose");
    if (live) return { field: f, state: "pass", sub: withDetail(CONDITION_STATE.liveCheck, f) };
    if (detail[f]) return { field: f, state: "neutral", sub: withDetail(CONDITION_STATE.recorded, f) };
    return { field: f, state: "neutral", sub: CONDITION_STATE.notRecorded };
  });
}

function Analysing({ steps, phase }: { steps: Steps; phase: Phase }) {
  const list: { key: StepKey; label: string; icon: IconName }[] = [
    { key: "upload", label: ANALYSIS_STEPS.upload, icon: "share" },
    { key: "analyse", label: ANALYSIS_STEPS.analyse, icon: "frame" },
    { key: "calibrate", label: ANALYSIS_STEPS.calibrate[phase], icon: "wave" },
    { key: "prepare", label: ANALYSIS_STEPS.prepare, icon: "file" },
  ];
  const doneCount = list.filter((s) => steps[s.key] === "done").length;
  const partial = steps.upload === "active" ? steps.uploadFraction : 0;
  const frac = (doneCount + partial) / list.length;
  const R = 64;
  const C = 2 * Math.PI * R;
  return (
    <div className="analysing">
      <svg className="ring" viewBox="0 0 160 160" role="img" aria-label={`${doneCount} of ${list.length} steps done`}>
        <circle cx="80" cy="80" r={R} className="ring__track" />
        <circle cx="80" cy="80" r={R} className="ring__value" strokeDasharray={C} strokeDashoffset={C * (1 - frac)} />
      </svg>
      <ol className="steps-list" aria-live="polite">
        {list.map((s) => (
          <li key={s.key} className={`step step--${steps[s.key]}`}>
            <Icon name={s.icon} size={20} />
            <span className="step__label">{s.label}</span>
            <span className="step__mark" aria-label={steps[s.key] === "done" ? "done" : steps[s.key] === "active" ? "in progress" : "waiting"}>
              {steps[s.key] === "done" ? <Icon name="check" size={16} /> : <span className="step__dot" />}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
