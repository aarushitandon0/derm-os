// Live capture checks. MediaPipe Face Landmarker gives face size and head pose;
// a small canvas sample gives light level and evenness. The same numbers
// (face_ratio, yaw, pitch, roll) are sent with the photo for the fingerprint.
import { FaceLandmarker, FilesetResolver, type FaceLandmarkerResult } from "@mediapipe/tasks-vision";

const VERSION = "0.10.35";
const WASM = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION}/wasm`;
const MODEL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";

// Thresholds for the live guide (not the comparability gate, which is server-side).
// Face SIZE is no longer a framing rule for the user: the server crops and scales every photo
// the same way. The live check only makes sure the face is big enough for that (no upscaling)
// and that the crop fits inside the frame.
export const GUIDE = {
  yawMax: 8,
  pitchMax: 10,
  rollMax: 6,
  lumaMin: 0.28,
  lumaMax: 0.85,
  sideImbalanceMax: 0.18,
  // The browser's landmark box and the server's detector box differ a little, so the live
  // estimate has to clear the server's target with room to spare.
  sizeMargin: 1.1,
  fitMargin: 0.97,
};

/** The server's crop rule (GET /api/meta -> capture), with the SD numbers as a fallback. */
export interface CaptureRule {
  faceFrac: number;
  targetFacePx: number;
}
export const DEFAULT_RULE: CaptureRule = { faceFrac: 0.75, targetFacePx: 360 };

/** Average light of the trial's baseline photos, from their fingerprints. */
export interface BaselineLight {
  luma: number;
  warmth: number;
}
export interface LightTolerance {
  luminance: number;
  red_blue_ratio: number;
}

export interface GuideContext {
  width: number; // camera frame, px
  height: number;
  rule: CaptureRule;
}

let landmarkerPromise: Promise<FaceLandmarker> | null = null;

export function loadLandmarker(): Promise<FaceLandmarker> {
  if (!landmarkerPromise) {
    landmarkerPromise = (async () => {
      const files = await FilesetResolver.forVisionTasks(WASM);
      const opts = (delegate: "GPU" | "CPU") => ({
        baseOptions: { modelAssetPath: MODEL, delegate },
        runningMode: "VIDEO" as const,
        numFaces: 2,
        outputFacialTransformationMatrixes: true,
      });
      try {
        return await FaceLandmarker.createFromOptions(files, opts("GPU"));
      } catch {
        return await FaceLandmarker.createFromOptions(files, opts("CPU"));
      }
    })();
    landmarkerPromise.catch(() => (landmarkerPromise = null));
  }
  return landmarkerPromise;
}

export interface FaceMetrics {
  faces: number;
  faceRatio: number | null; // face width / frame width
  centred: boolean;
  yaw: number | null;
  pitch: number | null;
  roll: number | null;
  box: { x0: number; x1: number; y0: number; y1: number } | null; // normalised
}

const deg = (r: number) => (r * 180) / Math.PI;

export function faceMetrics(res: FaceLandmarkerResult): FaceMetrics {
  const faces = res.faceLandmarks?.length ?? 0;
  if (faces === 0)
    return { faces, faceRatio: null, centred: false, yaw: null, pitch: null, roll: null, box: null };
  const lm = res.faceLandmarks[0];
  let x0 = 1,
    x1 = 0,
    y0 = 1,
    y1 = 0;
  for (const p of lm) {
    if (p.x < x0) x0 = p.x;
    if (p.x > x1) x1 = p.x;
    if (p.y < y0) y0 = p.y;
    if (p.y > y1) y1 = p.y;
  }
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  const centred = Math.abs(cx - 0.5) < 0.12 && Math.abs(cy - 0.5) < 0.16 && x0 > 0.01 && x1 < 0.99 && y0 > 0.01 && y1 < 0.99;

  let yaw: number | null = null,
    pitch: number | null = null,
    roll: number | null = null;
  const m = res.facialTransformationMatrixes?.[0]?.data;
  if (m && m.length >= 16) {
    // Column-major 4x4; rotation part R[row][col] = m[col*4 + row].
    const r00 = m[0], r10 = m[1], r20 = m[2], r21 = m[6], r22 = m[10];
    pitch = deg(Math.atan2(r21, r22));
    yaw = deg(Math.asin(Math.max(-1, Math.min(1, -r20))));
    roll = deg(Math.atan2(r10, r00));
  }
  return { faces, faceRatio: x1 - x0, centred, yaw, pitch, roll, box: { x0, x1, y0, y1 } };
}

export interface LightMetrics {
  luma: number; // 0..1, cheek band of the face (or centre if no face)
  imbalance: number; // |left - right| / max
  warmth: number; // red / blue
  // Measured the way the server measures the fingerprint: the central region of the crop the
  // server would make (3:4 around the face, face at faceFrac of the width). Compared with the
  // baseline using the gate's own tolerances.
  gateLuma: number | null;
  gateWarmth: number | null;
}

const sampler = typeof document !== "undefined" ? document.createElement("canvas") : null;

function meanRGB(ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number) {
  const w = Math.max(1, Math.round(x1 - x0));
  const h = Math.max(1, Math.round(y1 - y0));
  const { data } = ctx.getImageData(Math.round(x0), Math.round(y0), w, h);
  let R = 0, G = 0, B = 0;
  const n = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    R += data[i];
    G += data[i + 1];
    B += data[i + 2];
  }
  return { r: R / n, g: G / n, b: B / n };
}

export function lightMetrics(video: HTMLVideoElement, box: FaceMetrics["box"], rule: CaptureRule = DEFAULT_RULE): LightMetrics | null {
  if (!sampler || !video.videoWidth) return null;
  const W = 160;
  const H = Math.round((video.videoHeight / video.videoWidth) * W);
  sampler.width = W;
  sampler.height = H;
  const ctx = sampler.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, W, H);
  const b = box ?? { x0: 0.3, x1: 0.7, y0: 0.3, y1: 0.65 };
  // Cheek-height band of the face, split into left and right halves.
  const sx = Math.max(0, Math.floor(b.x0 * W));
  const ex = Math.min(W, Math.ceil(b.x1 * W));
  const sy = Math.max(0, Math.floor((b.y0 + (b.y1 - b.y0) * 0.35) * H));
  const ey = Math.min(H, Math.ceil((b.y0 + (b.y1 - b.y0) * 0.8) * H));
  if (ex - sx < 4 || ey - sy < 4) return null;
  const { data } = ctx.getImageData(sx, sy, ex - sx, ey - sy);
  const w = ex - sx;
  let l = 0, ln = 0, r = 0, rn = 0, R = 0, B = 0;
  for (let i = 0; i < data.length; i += 4) {
    const y = (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) / 255;
    const col = (i / 4) % w;
    if (col < w / 2) {
      l += y;
      ln++;
    } else {
      r += y;
      rn++;
    }
    R += data[i];
    B += data[i + 2];
  }
  const L = l / ln, Rr = r / rn;

  let gateLuma: number | null = null;
  let gateWarmth: number | null = null;
  if (box) {
    const fw = (box.x1 - box.x0) * W;
    const cw = fw / rule.faceFrac;
    const ch = (cw * 4) / 3;
    if (cw <= W && ch <= H) {
      const cx = ((box.x0 + box.x1) / 2) * W;
      const cy = ((box.y0 + box.y1) / 2) * H;
      const left = Math.min(Math.max(cx - cw / 2, 0), W - cw);
      const top = Math.min(Math.max(cy - ch / 2, 0), H - ch);
      const m = meanRGB(ctx, left + cw * 0.3, top + ch * 0.3, left + cw * 0.7, top + ch * 0.65);
      gateLuma = (0.2126 * m.r + 0.7152 * m.g + 0.0722 * m.b) / 255;
      gateWarmth = m.b ? m.r / m.b : 99;
    }
  }
  return { luma: (L + Rr) / 2, imbalance: Math.abs(L - Rr) / Math.max(L, Rr, 1e-3), warmth: B ? R / B : 99, gateLuma, gateWarmth };
}

/**
 * Would the comparability gate call this light different from the baseline? Same rule and
 * tolerances as compare_conditions() in backend/app/evidence.py: brightness first, then colour.
 */
export type LightIssue = "darker" | "brighter" | "warmer" | "cooler";
export function baselineLightIssue(
  l: Pick<LightMetrics, "gateLuma" | "gateWarmth"> | null,
  base: BaselineLight | null | undefined,
  tol: LightTolerance | null | undefined
): LightIssue | null {
  if (!l || !base || !tol || l.gateLuma == null || l.gateWarmth == null) return null;
  if (Math.abs(base.luma - l.gateLuma) > tol.luminance) return l.gateLuma < base.luma ? "darker" : "brighter";
  if (base.warmth && Math.abs(base.warmth - l.gateWarmth) / base.warmth > tol.red_blue_ratio)
    return l.gateWarmth > base.warmth ? "warmer" : "cooler";
  return null;
}

export const LIGHT_ISSUE_HINT: Record<LightIssue, string> = {
  warmer: "Warmer light than your first photos. The spot where you took them works best.",
  cooler: "Cooler light than your first photos. The spot where you took them works best.",
  darker: "Darker than your first photos. The spot where you took them works best.",
  brighter: "Brighter than your first photos. The spot where you took them works best.",
};

export interface CheckItem {
  key: string;
  label: string;
  ok: boolean;
  hint: string;
}

export type FaceIssue = "none" | "several" | "edge" | "far" | "close";

/** Is the face usable for the server's crop? null = fine. */
export function faceIssue(f: FaceMetrics | null, ctx: GuideContext): FaceIssue | null {
  if (!f || f.faces === 0 || !f.box) return "none";
  if (f.faces > 1) return "several";
  const { x0, x1, y0, y1 } = f.box;
  if (x0 < 0.01 || x1 > 0.99 || y0 < 0.01 || y1 > 0.99) return "edge";
  const facePx = (x1 - x0) * ctx.width;
  if (facePx < ctx.rule.targetFacePx * GUIDE.sizeMargin) return "far";
  const cw = facePx / ctx.rule.faceFrac;
  if (cw > ctx.width * GUIDE.fitMargin || (cw * 4) / 3 > ctx.height * GUIDE.fitMargin) return "close";
  return null;
}

const FACE_HINT: Record<FaceIssue, string> = {
  none: "Face the camera so your whole face is in view.",
  several: "Only one face in view, please.",
  edge: "Move so your whole face is inside the frame.",
  far: "Hold the phone a little closer.",
  close: "Hold the phone a little further away.",
};

/** Can this camera ever give a face big enough for the crop without upscaling? */
export function cameraTooSmall(width: number, height: number, rule: CaptureRule = DEFAULT_RULE): boolean {
  const cw = (rule.targetFacePx * GUIDE.sizeMargin) / rule.faceFrac;
  return width < cw || height < (cw * 4) / 3;
}

export function checklist(f: FaceMetrics | null, l: LightMetrics | null, ctx: GuideContext, light: LightIssue | null = null): CheckItem[] {
  const fi = faceIssue(f, ctx);
  const poseOk =
    f?.yaw != null &&
    Math.abs(f.yaw) <= GUIDE.yawMax &&
    Math.abs(f.pitch ?? 99) <= GUIDE.pitchMax &&
    Math.abs(f.roll ?? 99) <= GUIDE.rollMax;
  const evenOk = !!l && l.luma >= GUIDE.lumaMin && l.luma <= GUIDE.lumaMax && l.imbalance <= GUIDE.sideImbalanceMax;
  const lightOk = evenOk && !light;

  let poseHint = "Look roughly straight at the camera.";
  if (f?.yaw != null && Math.abs(f.yaw) > GUIDE.yawMax) poseHint = "Turn your head to face the camera.";
  else if (f?.pitch != null && Math.abs(f.pitch) > GUIDE.pitchMax) poseHint = "Level your chin.";
  else if (f?.roll != null && Math.abs(f.roll) > GUIDE.rollMax) poseHint = "Keep your head upright, not tilted.";
  else if (poseOk) poseHint = "Straight on.";

  let lightHint = "Face a window or soft, even light.";
  if (l && l.luma < GUIDE.lumaMin) lightHint = "Too dark. Face a window or a brighter light.";
  else if (l && l.luma > GUIDE.lumaMax) lightHint = "Too bright. Step out of direct light.";
  else if (l && l.imbalance > GUIDE.sideImbalanceMax) lightHint = "One side of your face is in shadow. Turn toward the light.";
  else if (light) lightHint = LIGHT_ISSUE_HINT[light];
  else if (lightOk) lightHint = "Light looks good.";

  return [
    { key: "face", label: "One face, close enough", ok: fi === null, hint: fi ? FACE_HINT[fi] : "Good distance." },
    { key: "pose", label: "Roughly straight", ok: poseOk, hint: poseHint },
    { key: "light", label: "Light OK", ok: lightOk, hint: lightHint },
  ];
}

/**
 * Coarse camera label for the comparability gate: the camera track's label (or the
 * platform when the browser hides it) plus the capture resolution. USB vendor ids
 * like "(05ac:8514)" are dropped; nothing here identifies a person.
 */
export function deviceLabel(stream: MediaStream | null, width: number, height: number): string | null {
  const track = stream?.getVideoTracks()[0];
  const label = (track?.label ?? "").replace(/\([0-9a-f]{4}:[0-9a-f]{4}\)/gi, "").replace(/\s+/g, " ").trim();
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  const name = label || nav.userAgentData?.platform || navigator.platform || "";
  const res = width > 0 && height > 0 ? `${width}×${height}` : "";
  const out = [name, res].filter(Boolean).join(" · ").slice(0, 80);
  return out || null;
}
