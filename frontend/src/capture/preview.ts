// DEV ONLY: simulated capture states for screenshots and design review, with no camera and
// no face photo. Opened with `&preview=far|close|warm|countdown|lookaway|quality` on the
// capture route. Capture.tsx only reads this behind `import.meta.env.DEV`, so production
// builds drop it. The simulated numbers go through the real checklist() and gate-light rule.
import type { Capture, Comparability, Fingerprint } from "../api";
import type { BaselineLight, FaceMetrics, LightMetrics } from "./faceGuide";

export type PreviewKind = "far" | "close" | "warm" | "countdown" | "lookaway" | "quality";
const KINDS: PreviewKind[] = ["far", "close", "warm", "countdown", "lookaway", "quality"];

export interface Preview {
  kind: PreviewKind;
  res: { w: number; h: number };
  face: FaceMetrics;
  light: LightMetrics;
  baseline: BaselineLight;
  baseCaps: Pick<Capture, "place" | "fingerprint">[];
  counting: boolean;
  lookAway: boolean;
  shot?: { capture: Capture; comparability: Comparability | null; liveChecked: boolean };
}

export function readPreview(): PreviewKind | null {
  const q = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const v = q.get("preview") as PreviewKind | null;
  return v && KINDS.includes(v) ? v : null;
}

const W = 1080;
const H = 1440;

// Face width as a share of the frame width; height ~1.25x the width, centred a little high.
function face(ratio: number): FaceMetrics {
  const hN = (ratio * W * 1.25) / H;
  return {
    faces: 1,
    faceRatio: ratio,
    centred: true,
    yaw: 1.5,
    pitch: -2,
    roll: 0.8,
    box: { x0: 0.5 - ratio / 2, x1: 0.5 + ratio / 2, y0: 0.46 - hN / 2, y1: 0.46 + hN / 2 },
  };
}

const BASE: BaselineLight = { luma: 0.53, warmth: 1.36 };
const EVEN: LightMetrics = { luma: 0.55, imbalance: 0.05, warmth: 1.4, gateLuma: 0.54, gateWarmth: 1.38 };
const WARM: LightMetrics = { ...EVEN, warmth: 1.85, gateWarmth: 1.82 };

const fp = (o: Partial<Fingerprint>): Fingerprint => ({
  width: 480,
  height: 640,
  short_side: 480,
  luminance: 0.54,
  red_blue_ratio: 1.38,
  device: "Front Camera · 1080×1440",
  captured_hour: 9,
  face_ratio: 0.75,
  yaw: 1.5,
  pitch: -2,
  roll: 0.8,
  device_source: "client",
  hour_source: "client",
  face_px: 360,
  face_px_original: 486,
  face_pct_original: 45,
  original_width: W,
  original_height: H,
  ...o,
});

export function previewState(kind: PreviewKind): Preview {
  const baseCaps = [{ place: "window" as const, fingerprint: fp({ captured_hour: 9 }) }];
  const p: Preview = {
    kind,
    res: { w: W, h: H },
    face: face(0.45),
    light: EVEN,
    baseline: BASE,
    baseCaps,
    counting: false,
    lookAway: false,
  };
  if (kind === "far") p.face = face(0.24);
  if (kind === "close") p.face = face(0.8);
  if (kind === "warm") p.light = WARM;
  if (kind === "countdown") p.counting = true;
  if (kind === "lookaway") p.lookAway = true;
  if (kind === "quality") {
    p.shot = {
      liveChecked: true,
      capture: {
        id: "preview",
        phase: "checkin",
        taken_at: new Date().toISOString(),
        source: "replay",
        replay: { persona: "riya", set: "checkin", fixture: "preview", synthetic: true },
        masks: {},
        fingerprint: fp({ captured_hour: 10, face_px_original: 410, face_pct_original: 38 }),
        raw_scores: { redness: 61 },
        mode: "sd",
        place: null,
      },
      comparability: {
        comparable: true,
        reasons: [],
        fixes: [],
        checked: ["mode", "lighting", "face_size", "head_pose", "device", "time_of_day"],
        failed: [],
        not_compared: [],
      },
    };
  }
  return p;
}
