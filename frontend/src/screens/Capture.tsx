import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type Capture as Cap, type Comparability, type ConditionField, type Place } from "../api";
import {
  baselineLightIssue,
  cameraTooSmall,
  checklist,
  DEFAULT_RULE,
  deviceLabel,
  faceMetrics,
  lightMetrics,
  loadLandmarker,
  type BaselineLight,
  type CaptureRule,
  type CheckItem,
  type FaceMetrics,
  type LightMetrics,
} from "../capture/faceGuide";
import { previewState, readPreview, type Preview } from "../capture/preview";
import { ANALYSIS_STEPS, baselineWhere, CAPTURE, CONDITION, CONDITION_ROWS, CONDITION_STATE, PLACES, PRIVACY } from "../copy";
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
// Auto-capture: every check has to hold for HOLD_MS, then a short countdown ring runs.
const HOLD_MS = 1000;
const COUNTDOWN_MS = 1200;
// Between baseline shots the guide waits until the face has left the checks for this long.
const LOOK_AWAY_MS = 250;
// Light is smoothed over frames so the baseline-light hint doesn't flicker.
const LIGHT_SMOOTHING = 0.35;
// After the last real step finishes, keep the finished list on screen briefly so it can be read.
const SETTLE_MS = 450;
const FRESH: Steps = { upload: "pending", analyse: "pending", calibrate: "pending", prepare: "pending", uploadFraction: 0 };

interface Shot {
  capture: Cap;
  comparability: Comparability | null;
  liveChecked: boolean; // the live MediaPipe checks passed before the shutter (not for file uploads)
}

const prefersReducedMotion = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function averageLight(caps: Cap[]): BaselineLight | null {
  const l = caps.map((c) => c.fingerprint?.luminance).filter((v): v is number => typeof v === "number");
  const w = caps.map((c) => c.fingerprint?.red_blue_ratio).filter((v): v is number => typeof v === "number");
  if (!l.length || !w.length) return null;
  const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
  return { luma: avg(l), warmth: avg(w) };
}

export default function Capture({ phase, trialId }: { phase: Phase; trialId?: string }) {
  const { health, meta, refresh } = useStore();
  const demo = !!health?.demo_mode;
  const total = SHOTS[phase];
  const exitTo = trialId ? `/trial/${trialId}` : "/";
  // DEV only: simulated states for screenshots (see capture/preview.ts). Dropped from production builds.
  const preview: Preview | null = useMemo(() => {
    if (!import.meta.env.DEV) return null;
    const kind = readPreview();
    return kind ? previewState(kind) : null;
  }, []);

  const rule: CaptureRule = meta?.capture
    ? { faceFrac: meta.capture.face_frac, targetFacePx: meta.capture.target_face_px.sd }
    : DEFAULT_RULE;
  const tol = meta?.tolerances
    ? { luminance: meta.tolerances.luminance, red_blue_ratio: meta.tolerances.red_blue_ratio }
    : null;

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const metricsRef = useRef<FaceMetrics | null>(null);
  const alive = useRef(true);
  // Auto-capture timing, read inside the frame loop.
  const passSince = useRef<number | null>(null);
  const countSince = useRef<number | null>(null);
  const awaySince = useRef<number | null>(null);
  const lookAwayRef = useRef<"waiting" | "away" | null>(null);
  const lightRef = useRef<{ gateLuma: number; gateWarmth: number } | null>(null);
  const shootRef = useRef<() => void>(() => {});
  const ctxRef = useRef({ rule, tol, baseLight: null as BaselineLight | null, tooLow: false });

  const [stage, setStage] = useState<Stage>("starting");
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<{ w: number; h: number } | null>(null);
  const [checks, setChecks] = useState<CheckItem[]>(() => checklist(null, null, { width: 0, height: 0, rule }));
  const [ready, setReady] = useState(false);
  const [counting, setCounting] = useState(false);
  const [lookAway, setLookAway] = useState(false);
  const [guideState, setGuideState] = useState<"loading" | "ok" | "failed">("loading");
  const [done, setDone] = useState(0);
  const [steps, setSteps] = useState<Steps>(FRESH);
  const [shot, setShot] = useState<Shot | null>(null);
  const [restarted, setRestarted] = useState(false);
  const [fixtureSet, setFixtureSet] = useState<string>("");
  const [place, setPlace] = useState<Place | null>(null);
  const [baseCaps, setBaseCaps] = useState<Pick<Cap, "place" | "fingerprint">[]>([]);
  const reduceMotion = useMemo(prefersReducedMotion, []);

  const tooLow = !!res && cameraTooSmall(res.w, res.h, rule);
  const baseLight = useMemo(() => (phase === "checkin" ? averageLight(baseCaps as Cap[]) : null), [phase, baseCaps]);
  ctxRef.current = { rule, tol, baseLight, tooLow };
  const where = phase === "checkin" ? baselineWhere(baseCaps) : null;

  useEffect(
    () => () => {
      alive.current = false;
    },
    []
  );

  // ------------------------------------------------------------ the trial's baseline (check-ins)
  useEffect(() => {
    if (preview) {
      setBaseCaps(preview.baseCaps);
      return;
    }
    if (phase !== "checkin" || !trialId) return;
    api.evidence(trialId).then(
      (ev) => alive.current && setBaseCaps(ev.captures.baseline),
      () => undefined // no hint without a baseline; the gate still checks after the photo
    );
  }, [phase, trialId, preview]);

  // ------------------------------------------------------------ one frame of checks
  const evaluate = useCallback(
    (f: FaceMetrics, l: LightMetrics | null, width: number, height: number, t: number) => {
      const c = ctxRef.current;
      metricsRef.current = f;
      if (l?.gateLuma != null && l.gateWarmth != null) {
        const s = lightRef.current;
        lightRef.current = s
          ? {
              gateLuma: s.gateLuma + LIGHT_SMOOTHING * (l.gateLuma - s.gateLuma),
              gateWarmth: s.gateWarmth + LIGHT_SMOOTHING * (l.gateWarmth - s.gateWarmth),
            }
          : { gateLuma: l.gateLuma, gateWarmth: l.gateWarmth };
      }
      // Never during the baseline itself: there is nothing to match yet.
      const issue = phase === "checkin" ? baselineLightIssue(lightRef.current, c.baseLight, c.tol) : null;
      const items = checklist(f, l, { width, height, rule: c.rule }, issue);
      setChecks(items);
      const allOk = items.every((i) => i.ok) && !c.tooLow;
      setReady(allOk);

      const cancel = () => {
        passSince.current = null;
        if (countSince.current !== null) {
          countSince.current = null;
          setCounting(false);
        }
      };
      // Between baseline shots: wait for a look away, then for the face to come back.
      if (lookAwayRef.current === "waiting") {
        cancel();
        if (!allOk) {
          awaySince.current ??= t;
          if (t - awaySince.current >= LOOK_AWAY_MS) lookAwayRef.current = "away";
        } else awaySince.current = null;
        return;
      }
      if (!allOk) return cancel();
      if (lookAwayRef.current === "away") {
        lookAwayRef.current = null;
        setLookAway(false);
      }
      passSince.current ??= t;
      if (countSince.current === null && t - passSince.current >= HOLD_MS) {
        countSince.current = t;
        setCounting(true);
      }
      if (countSince.current !== null && t - countSince.current >= COUNTDOWN_MS) {
        cancel();
        shootRef.current();
      }
    },
    [phase]
  );

  // ------------------------------------------------------------ preview (DEV only)
  useEffect(() => {
    if (!preview) return;
    setRes(preview.res);
    setGuideState("ok");
    lightRef.current = { gateLuma: preview.light.gateLuma!, gateWarmth: preview.light.gateWarmth! };
    const issue = phase === "checkin" ? baselineLightIssue(lightRef.current, preview.baseline, tol) : null;
    const items = checklist(preview.face, preview.light, { width: preview.res.w, height: preview.res.h, rule }, issue);
    setChecks(items);
    setReady(items.every((i) => i.ok));
    setCounting(preview.counting);
    if (preview.lookAway) {
      setDone(1);
      setLookAway(true);
    }
    if (preview.shot) {
      setShot(preview.shot);
      setDone(1);
      setStage("quality");
    } else setStage("live");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, meta]);

  // ------------------------------------------------------------ camera
  useEffect(() => {
    if (preview) return;
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
  }, [preview]);

  // ------------------------------------------------------------ live checks
  useEffect(() => {
    if (stage !== "live" || preview) return;
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
      evaluate(f, lightMetrics(v, f.box, ctxRef.current.rule), v.videoWidth, v.videoHeight, t);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      stop = true;
      cancelAnimationFrame(raf);
      passSince.current = null;
      countSince.current = null;
      setCounting(false);
    };
  }, [stage, evaluate, preview]);

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
            place: phase === "baseline" ? place : null,
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
        // Baseline: straight back to the camera for the next shot, after a look away.
        if (phase === "baseline" && n < total) {
          lookAwayRef.current = "waiting";
          awaySince.current = null;
          setLookAway(true);
          setStage("live");
          return;
        }
        await new Promise((ok) => setTimeout(ok, SETTLE_MS));
        if (alive.current) setStage("quality");
      } catch (e) {
        if (!alive.current) return;
        setError(e instanceof ApiError ? e.message : "The scan didn't go through. Try again.");
        setStage("live");
      }
    },
    [phase, trialId, demo, fixtureSet, done, total, refresh, place]
  );

  const shoot = () => {
    const v = videoRef.current;
    if (!v || preview || stage !== "live" || !v.videoWidth) return;
    passSince.current = null;
    countSince.current = null;
    setCounting(false);
    const c = document.createElement("canvas");
    c.width = v.videoWidth; // full camera resolution, not the preview size
    c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    const m = metricsRef.current;
    // The canvas JPEG has no EXIF, so record the local hour and a coarse camera label now.
    const taken = { hour: new Date().getHours(), device: deviceLabel(streamRef.current, c.width, c.height) };
    c.toBlob((b) => b && upload(b, m, true, taken), "image/jpeg", 0.92);
  };
  shootRef.current = shoot;

  const fromFile = (file: File | undefined) => file && upload(file, null, false);

  const backToLive = () => {
    passSince.current = null;
    countSince.current = null;
    setReady(false);
    setCounting(false);
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
          {demo ? PRIVACY.demo : PRIVACY.live} <a href={href("/learn?section=data")}>Manage saved scans</a>
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
        : `All ${total} baseline photos saved. These are the conditions to match at each check-in.`;
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
        {import.meta.env.DEV && preview && <p className="small muted">Dev preview: simulated capture, no photo.</p>}
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
  const hint =
    guideState === "loading"
      ? "Loading the face guide…"
      : lookAway
      ? CAPTURE.lookAway(done, total)
      : (checks.find((c) => !c.ok) ?? checks[0]).hint;
  const shutterLabel = counting ? CAPTURE.holdStill : shutterEnabled ? CAPTURE.auto : CAPTURE.waiting;
  const lede =
    phase === "baseline" ? CAPTURE.baselineLede : where ? `${where}. ${CAPTURE.sameSpot}` : CAPTURE.checkinLede;

  // The camera stays mounted through every stage so the stream survives between photos.
  const showCamera = stage === "starting" || stage === "live" || stage === "error";
  return (
    <div className={`page page--flow${showCamera ? " page--capture" : ""}`}>
      {nav}
      {analysingView}
      {qualityView}
      <div hidden={!showCamera}>
        <PageHead title={phase === "baseline" ? "Take your baseline" : "Take your check-in"} lede={lede} />
        {restarted && phase === "checkin" && stage === "live" && (
          <Notice>Retaking both check-in photos, so the pair matches your baseline.</Notice>
        )}

        <div className={`viewfinder${ready ? " viewfinder--ready" : ""}`}>
          <video ref={videoRef} playsInline muted className="viewfinder__video" />
          <svg className="viewfinder__guide" viewBox="0 0 300 400" preserveAspectRatio="none" aria-hidden>
            <ellipse cx="150" cy="190" rx="92" ry="128" />
          </svg>
          {stage === "starting" && <p className="viewfinder__msg">Opening camera…</p>}
          {stage === "error" && <p className="viewfinder__msg">Camera unavailable</p>}
          {import.meta.env.DEV && preview && <p className="viewfinder__msg">Dev preview: simulated camera, no photo</p>}
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
          {hint}
        </p>

        {tooLow && <Notice tone="stop">{CAPTURE.cameraTooSmall}</Notice>}
        {guideState === "failed" && (
          <Notice tone="warn">The face guide couldn't load (it needs a connection the first time). Reload to try again.</Notice>
        )}
        {error && <Notice tone="stop">{error}</Notice>}

        <div className="shutterwrap">
          <div className={`shutterbox${counting ? " is-counting" : ""}`}>
            {counting && (
              <svg className={`countdown${reduceMotion ? " countdown--still" : ""}`} viewBox="0 0 100 100" aria-hidden>
                <circle cx="50" cy="50" r="46" pathLength={100} />
              </svg>
            )}
            <button className="shutter" disabled={!shutterEnabled} onClick={shoot} aria-label="Take photo now">
              <span className="shutter__ring" />
            </button>
          </div>
          <p className="shutter__label" aria-live="polite">
            {shutterLabel}
          </p>
        </div>

        {phase === "baseline" && (
          <fieldset className="placepick">
            <legend className="placepick__q">{CAPTURE.placeQuestion}</legend>
            <div className="chips">
              {PLACES.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  className={`symchip${place === p.value ? " is-on" : ""}`}
                  aria-pressed={place === p.value}
                  onClick={() => setPlace(place === p.value ? null : p.value)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="formhelp">{CAPTURE.placeWhy}</p>
          </fieldset>
        )}

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

const SHORT: Record<string, string> = { face: "Face", pose: "Straight", light: "Light" };

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

  const faceDetail =
    typeof fp.face_pct_original === "number"
      ? `cropped to the standard size (your face was ${Math.round(fp.face_pct_original)}% of the photo)`
      : typeof fp.face_ratio === "number"
      ? `${Math.round(fp.face_ratio * 100)}% of frame width`
      : null;
  const detail: Partial<Record<ConditionField, string | null>> = {
    lighting: typeof fp.luminance === "number" ? `brightness ${fp.luminance.toFixed(2)}` : null,
    face_size: faceDetail,
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
      if (c.checked?.includes(f)) return { field: f, state: "pass", sub: withDetail(CONDITION_STATE.match, f) };
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
