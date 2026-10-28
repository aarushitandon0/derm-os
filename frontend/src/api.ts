// Typed client for the derm//os FastAPI backend. Shapes mirror backend/app/*.py.
import { readLocal, writeLocal } from "./local";

// Empty in dev (Vite proxies /api and /media). On Vercel: the Render URL, no trailing slash.
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").trim().replace(/\/+$/, "");
const apiUrl = (path: string) => API_BASE + path;
/** Server-relative media paths (saved YouCam masks) resolved against the API origin. */
export const assetUrl = (u: string | undefined | null) => (u && u.startsWith("/") ? API_BASE + u : u ?? undefined);

const UNREACHABLE = API_BASE
  ? "Can't reach the derm//os server. It may be waking up; try again in a minute."
  : "Can't reach the derm//os server. Is the backend running on port 8000?";

// Live scans need DEMO_MODE=0 on the server AND this passcode. Kept on this device only.
const PASSCODE_KEY = "livePasscode";
export const livePasscode = () => readLocal<string>(PASSCODE_KEY, "");
export const setLivePasscode = (code: string) => writeLocal(PASSCODE_KEY, code.trim());
const passHeaders = (): Record<string, string> => {
  const code = livePasscode();
  return code ? { "X-Live-Passcode": code } : {};
};

export type Role = "cleanser" | "toner" | "serum" | "treatment" | "moisturiser" | "sunscreen";

export interface Product {
  id: string;
  name: string;
  brand: string;
  role: Role;
  leave_on: boolean;
  price_inr: number;
  inci: string[];
  inci_complete: boolean;
  source: string;
}

export type RecordType = "suspected_reaction" | "avoid" | "confirmed_allergy";

export interface HistoryRecord {
  id: string;
  type: RecordType;
  product_id?: string | null;
  ingredient?: string | null;
  note: string;
}

// nothing_to_check: no ingredient exclusions recorded yet. Neutral, never a pass.
export type CheckStatus = "pass" | "blocked" | "unknown" | "nothing_to_check";
export interface Check {
  product_id: string;
  status: CheckStatus;
  reasons: string[];
  matches: { label_line: string | null; matched: string; record: RecordType }[];
  // Shown whatever the status: "ingredient_list_incomplete" when the label isn't fully known.
  tags?: string[];
}

export interface Question {
  id: string;
  text: string;
  choices: string[];
  why: string;
}

export interface Column {
  name: string;
  steps: string[];
  added: string[];
  replaced: { out: string; in: string }[];
  kept: string[];
  stopped: string[]; // products you'd stop using (replaced ones)
  step_count: number; // steps after the change
  new_spend_inr: number; // the new product's price: you buy it whether it adds or replaces
  duplicate_roles: string[];
  checks: Check[];
  blocked: boolean;
  unknowns: string[];
  new_leave_on: number;
  open_questions: Question[];
}

export interface CompareResult {
  columns: Column[];
  next_question: Question | null;
  rule_version: string;
}

export interface Checkin {
  symptoms: string[];
  other_new_leave_on: string[];
  at: string;
}

export interface Trial {
  id: string;
  goal_concern: string;
  product_id: string;
  held_fixed: string[];
  checkpoints_days: number[];
  status: string;
  check: Check;
  started_at: string;
  checkins: Checkin[];
}

export interface Range {
  lo: number;
  hi: number;
  n: number;
  width: number;
}

export interface Finding {
  concern: string;
  baseline: Range | null;
  followup: Range | null;
  direction: "better" | "worse" | null;
  delta_mid: number | null;
  beyond_noise: boolean;
}

export type VerdictCode =
  | "stop_reaction"
  | "cant_tell_no_baseline"
  | "cant_tell_not_comparable"
  | "cant_tell_several_changes"
  | "no_detectable_change"
  | "moved_beyond_noise";

export type ConditionField = "mode" | "lighting" | "face_size" | "head_pose" | "device" | "time_of_day";

export interface Comparability {
  comparable: boolean;
  reasons: string[];
  fixes: string[];
  // Same result per field: which had data on both sides, and each mismatch with its fix.
  checked?: ConditionField[];
  failed?: { field: ConditionField; reason: string; fix: string }[];
  // Data on both sides but not comparable fairly (e.g. camera labels from different sources). Never fails the pair.
  not_compared?: { field: ConditionField; reason: string }[];
}

export interface Reaction {
  id: string;
  symptom: string;
  logged_at: string;
  last_logged_at: string;
  resolved: boolean;
  resolved_on: string | null;
  resolution_note: string;
}

export interface Report {
  verdict: VerdictCode;
  message: string;
  findings: Finding[];
  comparability: Comparability | null;
  symptoms: string[];
  rule_version: string;
}

export interface Fingerprint {
  width: number;
  height: number;
  short_side: number;
  luminance: number;
  red_blue_ratio: number;
  device: string | null;
  captured_hour: number | null;
  face_ratio: number | null;
  yaw: number | null;
  pitch: number | null;
  roll: number | null;
  // Where device / hour came from: the photo's EXIF, or the phone at capture time.
  device_source?: "exif" | "client" | null;
  hour_source?: "exif" | "client" | null;
  // Every capture is cropped and scaled the same way first; both face sizes are kept.
  face_px?: number | null; // in the normalised capture (the same for every capture in a mode)
  face_px_original?: number | null;
  face_pct_original?: number | null; // % of the original photo's width
  original_width?: number | null;
  original_height?: number | null;
  face_ratio_live?: number | null;
}

export interface Capture {
  id: string;
  phase: "baseline" | "checkin" | "free";
  taken_at: string;
  source: "live" | "replay";
  replay: { persona: string; set: string; fixture: string; synthetic: boolean } | null;
  masks: Record<string, string[]>;
  fingerprint: Fingerprint;
  raw_scores: Record<string, number>;
  mode: string;
  place?: Place | null;
}

/** Where the baseline was taken, if the user said. Never inferred. */
export type Place = "window" | "ceiling" | "lamp" | "outdoors" | "other";

export interface Evidence {
  trial: Trial;
  report: Report;
  product: Product;
  captures: { baseline: Capture[]; followup: Capture[] };
  reactions: Reaction[];
  // Every scan in order; each check-in gated against the baseline on its own (null = not a check-in).
  series: (Capture & { comparable: boolean | null })[];
  baseline_ranges: Record<string, Range>;
  timeline: { at: string; kind: string; text: string }[];
}

export interface Health {
  ok: boolean;
  youcam_key: boolean;
  /** True unless THIS device's scans really go to YouCam (server live + right passcode). */
  demo_mode: boolean;
  server_demo_mode?: boolean;
  live_scans?: "off" | "passcode" | "disabled";
  passcode?: "none" | "ok" | "wrong";
  personas: Record<string, string[]>;
  unit_reserve: number;
  rules?: string[];
  /** Whether the optional language layer (intake + explanations) is on. */
  llm?: boolean;
}

export interface Proposal {
  id: string;
  type: RecordType;
  product_id: string | null;
  product_text: string | null;
  product_matched: boolean;
  ingredient: string | null;
  note: string;
  needs_confirmation: ("type" | "product_id" | "ingredient")[];
  hints: string[];
  quote: string;
}

export interface IntakeResult {
  available: boolean;
  proposals: Proposal[];
  rejected: string | null;
  dropped: number;
}

export interface Explanation {
  text: string;
  source: "llm" | "template";
  rejected: string | null;
}

export interface Meta {
  stop_symptoms: string[];
  verdict_text: Record<VerdictCode, string>;
  tolerances: Record<string, number>;
  min_band: number;
  // The server's crop and scale (app/facecrop.py), so the live guide uses the same numbers.
  capture?: { face_frac: number; target_face_px: Record<"sd" | "hd", number>; output: Record<"sd" | "hd", number[]> };
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

function detailText(body: any, status: number): string {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d.message === "string") return d.message;
  if (Array.isArray(d)) return d.map((x) => x.msg).join("; ");
  return `Request failed (${status})`;
}

export type ScanResult = { capture: Capture; comparability: Comparability | null };

// The scan as an XHR so the screen can follow the real upload, then the wait for the analysis.
function scanRequest(body: FormData, onUploaded?: (fraction: number, done: boolean) => void): Promise<ScanResult> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", apiUrl("/api/scan"));
    for (const [k, v] of Object.entries(passHeaders())) x.setRequestHeader(k, v);
    let uploaded = false;
    const markUploaded = () => {
      if (!uploaded) {
        uploaded = true;
        onUploaded?.(1, true);
      }
    };
    x.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onUploaded?.(Math.min(e.loaded / e.total, 1), false);
    };
    x.upload.onload = markUploaded;
    x.onerror = () => reject(new ApiError(0, UNREACHABLE));
    x.onload = () => {
      markUploaded();
      let data: any = null;
      try {
        data = JSON.parse(x.responseText);
      } catch {
        data = null;
      }
      if (x.status >= 200 && x.status < 300 && data) resolve(data as ScanResult);
      else reject(new ApiError(x.status, detailText(data, x.status), data));
    };
    x.send(body);
  });
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(apiUrl(path), { ...init, headers: { ...passHeaders(), ...(init?.headers as Record<string, string>) } });
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(r.status, detailText(body, r.status), body);
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

export interface ScanInput {
  image: Blob;
  phase: "baseline" | "checkin" | "free";
  trialId?: string;
  actions?: string[];
  faceRatio?: number | null;
  yaw?: number | null;
  pitch?: number | null;
  roll?: number | null;
  persona?: string;
  fixtureSet?: string | null;
  // Live camera shots only: canvas JPEGs carry no EXIF, so the phone says when and with what.
  clientHour?: number | null;
  clientDevice?: string | null;
  place?: Place | null;
}

export const api = {
  health: () => call<Health>("/api/health"),
  meta: () => call<Meta>("/api/meta"),
  catalog: () => call<Product[]>("/api/catalog"),
  shelf: () => call<{ product_ids: string[] }>("/api/shelf"),
  setShelf: (ids: string[]) => call<{ product_ids: string[] }>("/api/shelf", json("PUT", { product_ids: ids })),
  history: () => call<HistoryRecord[]>("/api/history"),
  addRecord: (r: Omit<HistoryRecord, "id">) => call<HistoryRecord>("/api/history", json("POST", r)),
  intake: (text: string) => call<IntakeResult>("/api/history/intake", json("POST", { text })),
  explanation: (trialId: string) => call<Explanation>(`/api/trials/${trialId}/explanation`),
  removeRecord: (id: string) => call<unknown>(`/api/history/${id}`, { method: "DELETE" }),
  compare: (options: { name: string; items: { product_id: string; mode?: "add" | "replace" | null }[] }[]) =>
    call<CompareResult>("/api/compare", json("POST", { options })),
  trials: () => call<Trial[]>("/api/trials"),
  trial: (id: string) => call<Trial>(`/api/trials/${id}`),
  startTrial: (t: { goal_concern: string; product_id: string; held_fixed: string[]; checkpoints_days?: number[] }) =>
    call<Trial>("/api/trials", json("POST", t)),
  checkin: (id: string, c: { symptoms: string[]; other_new_leave_on: string[] }) =>
    call<Trial>(`/api/trials/${id}/checkin`, json("POST", c)),
  evidence: (id: string) => call<Evidence>(`/api/trials/${id}/evidence`),
  resolveReaction: (trialId: string, reactionId: string, body: { resolved_on?: string; note?: string }) =>
    call<{ reaction: Reaction; reactions: Reaction[] }>(
      `/api/trials/${trialId}/reactions/${encodeURIComponent(reactionId)}/resolve`,
      json("POST", body)
    ),
  deleteCaptures: () =>
    call<{
      deleted: number;
      youcam: { already_deleted: number; requested: number; deleted: number; failed: number; skipped_reason: string | null };
    }>("/api/captures", { method: "DELETE" }),
  demoReset: () => call<unknown>("/api/demo/reset", { method: "POST" }),
  scan: (s: ScanInput, onUploaded?: (fraction: number, done: boolean) => void) => {
    const f = new FormData();
    f.append("image", s.image, "capture.jpg");
    f.append("phase", s.phase);
    f.append("actions", (s.actions ?? DEFAULT_ACTIONS).join(","));
    if (s.trialId) f.append("trial_id", s.trialId);
    for (const [k, v] of [["face_ratio", s.faceRatio], ["yaw", s.yaw], ["pitch", s.pitch], ["roll", s.roll]] as const) {
      if (v !== null && v !== undefined && Number.isFinite(v)) f.append(k, String(v));
    }
    if (typeof s.clientHour === "number" && s.clientHour >= 0 && s.clientHour <= 23)
      f.append("client_hour", String(Math.floor(s.clientHour)));
    if (s.clientDevice) f.append("client_device", s.clientDevice);
    if (s.persona) f.append("persona", s.persona);
    if (s.fixtureSet) f.append("fixture_set", s.fixtureSet);
    if (s.place) f.append("place", s.place);
    return scanRequest(f, onUploaded);
  },
};

export const DEFAULT_ACTIONS = ["redness", "texture", "acne", "pore", "oiliness", "moisture"];
export const CONCERNS = DEFAULT_ACTIONS;
