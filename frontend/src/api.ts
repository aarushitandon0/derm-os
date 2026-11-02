// Typed client for the derm//os FastAPI backend. Shapes mirror backend/app/*.py.
import { mirrorRecord, readLocal, writeLocal } from "./local";

// Empty in dev (Vite proxies /api and /media). On Vercel: the Render URL, no trailing slash.
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").trim().replace(/\/+$/, "");
const apiUrl = (path: string) => API_BASE + path;
/** Server-relative media paths (saved YouCam masks) resolved against the API origin. */
export const assetUrl = (u: string | undefined | null) => (u && u.startsWith("/") ? API_BASE + u : u ?? undefined);

export const UNREACHABLE = API_BASE
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
  /** What the product's own claims are aimed at, in YouCam concern names. Never a measured effect. */
  aimed_at?: string[];
  source: string;
}

// ---------------------------------------------------------------- outcomes (what happened)
export type OutcomeValue = "suited" | "irritation" | "breakout" | "not_sure";
/** What an outcome reads as once the >= 4 week rule is applied (backend app/outcomes.py). */
export type EffectiveOutcome = OutcomeValue | "too_early";
export type FaceZone = "forehead" | "nose" | "cheeks" | "chin" | "jaw";

export interface ProductOutcome {
  id: string;
  product_id: string;
  outcome: OutcomeValue;
  leave_on: boolean;
  started_on: string | null;
  stopped_on: string | null;
  weeks_used_given: number | null;
  zones: FaceZone[];
  usual_spots: boolean | null;
  settled_while_using: boolean | null;
  settled_week: number | null;
  note: string;
  source: "user" | "writeback";
  trial_id: string | null;
  rule_version: string;
  // Derived by the backend, never recomputed here.
  weeks_used: number | null;
  effective_outcome: EffectiveOutcome;
  label: string;
  plain_line: string;
  counts_as_suited: boolean;
}

export interface OutcomeIn {
  product_id: string;
  outcome: OutcomeValue;
  started_on?: string | null;
  stopped_on?: string | null;
  weeks_used_given?: number | null;
  zones?: FaceZone[];
  usual_spots?: boolean | null;
  settled_while_using?: boolean | null;
  settled_week?: number | null;
  note?: string;
}

// ---------------------------------------------------------------- patterns
export type PatternTier = "suspect" | "lead" | "cleared_so_far";

export interface Appearance {
  product_id: string;
  product_name: string;
  label_line: string;
  inci_position: number;
  inci_length: number;
  leave_on: boolean;
  weight: number;
  weight_label: string | null;
}

export interface Suspect {
  ingredient: string;
  display: string;
  tier: PatternTier;
  tier_label: string;
  match_type: "exact" | "family";
  family: string | null;
  family_label: string | null;
  /** "personal" (your own records) or "general" (general knowledge). Kept apart on purpose. */
  evidence: string;
  general_note: string | null;
  in_failed: Appearance[];
  in_suited: Appearance[];
  failed_count: number;
  failed_total: number;
  suited_count: number;
  suited_total: number;
  failed_weight: number;
  counts_line: string;
}

export interface PurgeOffer {
  product_id: string;
  product_name: string;
  ingredient: string;
  label_line: string;
  strength: "can" | "mild";
  settled_week: number | null;
  question: string;
  note: string;
}

export interface PatternReport {
  kind: "irritation" | "breakout";
  headline: string;
  suspects: Suspect[];
  failed_products: (ProductOutcome & { product_name: string; inci_length: number | null })[];
  suited_products: (ProductOutcome & { product_name: string; inci_length: number | null })[];
  cannot_narrow: string | null;
  only_in_failed: { ingredient: string; display: string; match_type: string; inci_position: number }[];
  incomplete_products: { product_id: string; product_name: string; listed: number; note: string }[];
  unknown_note: string | null;
  purge_offers: PurgeOffer[];
  rule_version: string;
  families_version: string;
}

export interface Patterns {
  irritation: PatternReport;
  breakout: PatternReport;
  rule_version: string;
  families_version: string;
}

// ---------------------------------------------------------------- cart check (before you buy)
export type CartRung = "blocked" | "repeats_a_pattern" | "patch_test_first" | "no_conflicts";

export interface CartSource {
  key: "history" | "skin" | "shelf";
  label: string;
  lines: string[];
  detail: Record<string, any>;
}

export interface CartCheck {
  product_id: string;
  rung: CartRung;
  rung_label: string;
  /** What the screen prints. Reads "Ingredient list incomplete -> unknown" when `unknown`. */
  verdict_line: string;
  tags: string[];
  unknown: boolean;
  sources: CartSource[];
  next_step: string;
  change_nothing: string;
  inputs: Record<string, any>;
  rule_version: string;
}

// ---------------------------------------------------------------- the basket (shop by your face)
export interface BasketQuestion {
  id: "finish" | "history" | "budget" | "veins";
  text: string;
  why: string;
  skippable?: boolean;
  choices: { value: string; label: string }[];
}
export interface BasketQuestions {
  questions: BasketQuestion[];
  on_record: { records: number; outcomes: number; bothered: number };
  rule_version: string;
}
export interface ZoneRead {
  zone: "t_zone" | "u_zone";
  name: string;
  type: "oily" | "dry" | "normal";
  redness: boolean;
  source: "face" | "answers";
  label: string;
  line: string;
}
export interface Shade {
  name: string;
  depth: string;
  undertone: string;
  hex: string;
}
/** "What your scan found" (backend app/findings.py, findings-1.0): words only, never a value. */
export interface ScanFindingLine {
  concern: string;
  band: "high" | "mid" | "low";
  line: string;
  need: { key: string; line: string; targets: string[] } | null;
  see_doctor: string | null;
}
export interface ScanFindings {
  lines: ScanFindingLine[];
  label: string;
  rule_version: string;
}
export interface FaceMapData {
  zones: ZoneRead[];
  same_type: boolean;
  needs: { key: string; line: string; zone: string; label: string }[];
  needs_line: string;
  see_doctor: string | null;
  undertone: { tone: string; depth: string; source: "face" | "answers" | "default"; label: string; line: string; note: string; skin_color: string | null };
  source: "face" | "answers";
  label: string;
  demo: boolean;
  findings?: ScanFindings | null;
}
export interface BasketWhy {
  key: "face" | "history" | "finish" | "shelf";
  label: string;
  line: string;
}
export interface BasketJob {
  job: "cleanser" | "moisturiser" | "base";
  zone: "whole" | "t_zone" | "u_zone";
  title: string;
  status: "pick" | "owned" | "none";
  how_to_use: string;
  pick: { product: Product; price_inr: number; shade: Shade | null; finish?: string; texture?: string } | null;
  why: BasketWhy[];
  also_fits: { product_id: string; name: string; brand: string; price_inr: number; patch_test_first: boolean }[];
  note: string | null;
  /** "Gentle start for new routines" on a beginner's basket. */
  label?: string;
  /** "Worked for you" lines and purge notes from the ingredient chips. */
  tried?: string[];
  look_for: LookFor;
}
/** What to look for on any label for the same job (app/lookfor.py). Never names a brand. */
export interface LookFor {
  ingredients: string[];
  texture: string | null;
  finish: string | null;
  shade: string | null;
  avoid: { what: string; why: string }[];
  worked: string[];
  lines: string[];
  rule_version: string;
}
// ---- quick history by ingredient (app/chips.py)
export type ChipReaction = "itched" | "broke_out" | "comedones" | "suited" | "not_sure";
export interface ChipIn {
  chip: string;
  reaction: ChipReaction;
  product_name?: string;
  confirmed_allergy?: boolean;
  usual_spots_settled?: "yes" | "no" | "not_sure" | null;
  purge_choice?: "purging" | "breakout" | null;
}
export interface ChipOut extends Required<Omit<ChipIn, "usual_spots_settled" | "purge_choice">> {
  usual_spots_settled: "yes" | "no" | "not_sure" | null;
  purge_choice: "purging" | "breakout" | null;
  reaction_label: string;
  label: string;
  word: string;
  line: string;
  purge_question: string | null;
  purge_offer: string | null;
  purge_capable: boolean;
}
export interface ChipSpec {
  id: string;
  label: string;
  purge_capable: boolean;
}
export interface ChipsState {
  chips: ChipOut[];
  catalogue: ChipSpec[];
  reactions: Record<ChipReaction, string>;
  purge_question: string;
  rule_version: string;
}
// ---- start plan (app/startplan.py)
export interface StartStep {
  order: number;
  product_id: string;
  name: string;
  job: string;
  group: string;
  patch_from: string;
  patch_to: string;
  start_on: string;
  line: string;
}
export interface StartPlan {
  title: string;
  patch_line: string;
  spacing_line: string;
  steps: StartStep[];
  keep: { product_id: string; name: string; job: string; line: string }[];
  if_reacts: string;
  sources: { id: string; text: string; url: string }[];
  today: string;
  rule_version: string;
}
// ---- check any product (app/pastecheck.py). Nothing is stored.
export type PasteJob = "cleanser" | "moisturiser" | "sunscreen" | "serum";
export interface PasteResult {
  name: string;
  job: PasteJob;
  rung: string;
  verdict_line: string;
  unknown: boolean;
  complete: boolean;
  lines: string[];
  parse_notes: string[];
  sources: { key: "history" | "tried" | "fit"; label: string; lines: string[] }[];
  next_step: string;
  stored: false;
  rule_version: string;
}
export interface BasketSkip {
  product_id: string;
  name: string;
  brand: string;
  job: string;
  kind: "history" | "tried" | "unknown" | "finish" | "shade" | "zone" | "budget";
  label: string;
  reason: string;
  all_reasons?: string[];
}
export interface TryOn {
  status: "ready" | "pending_live" | "no_shade";
  line: string | null;
  product?: Product | null;
  shade?: Shade;
  undertone?: string;
  looks: { look: "matte" | "dewy"; label: string; glow: number; image: string | null }[];
}
export interface Basket {
  id: string;
  source: "live" | "replay";
  demo_label?: string;
  notice?: string | null;
  /** Built from a logged-in user's saved history and shelf. */
  from_profile?: boolean;
  face_map: FaceMapData;
  jobs: BasketJob[];
  skipped: BasketSkip[];
  already_own: { product_id: string; name: string; brand: string; job: string; line: string }[];
  total_inr: number;
  next_step: string;
  tryon: TryOn;
  start_plan: StartPlan;
  tried: { chips: ChipOut[]; purge_questions: ChipOut[]; beginner: boolean; rule_version: string };
  beginner: boolean;
  rule_version: string;
}

export interface SaleItem {
  product_id: string;
  sale_price_inr: number;
  blurb: string;
  product: Product;
}

export interface Store {
  name: string;
  line: string;
  items: SaleItem[];
  disclaimer: string;
}

// ---------------------------------------------------------------- triage (after a breakout)
export interface TriageCandidate {
  product_id: string;
  product_name: string;
  leave_on: boolean;
  started_on: string | null;
  weeks_used: number | null;
  tier: number;
  reason: string;
  in_window: boolean;
  purge_capable: { label_line: string; ingredient: string; strength: string; note: string }[];
}

export interface Triage {
  stop: boolean;
  stop_symptoms: string[];
  headline: string;
  candidates: TriageCandidate[];
  purge: {
    possible: boolean;
    consistent: boolean;
    ingredient: string | null;
    label_line: string | null;
    strength: string | null;
    conditions: Record<string, unknown>;
    line: string;
  };
  zones: {
    source: "masks" | "tapped" | "none";
    source_note: string;
    zones: FaceZone[];
    usual_spots: boolean | null;
    shares: Record<string, number>;
    baseline_shares: Record<string, number>;
    line: string;
  };
  next_step: string;
  next_action: {
    kind: "stop_card" | "open_trial" | "add_products";
    pause_product_id?: string | null;
    keep_product_id?: string | null;
    hold_fixed?: string[];
    checkpoint_days?: number;
    brief?: boolean;
  };
  inputs: Record<string, any>;
  rule_version: string;
  families_version: string;
}

export interface TriageIn {
  symptoms?: string[];
  zones?: FaceZone[];
  usual_spots?: boolean | null;
  using?: { product_id: string; started_on?: string | null }[];
  settled_while_using?: boolean | null;
  settled_week?: number | null;
}

/** What a demo scene says the person is dealing with. Never a verdict: the engines do that. */
export interface SceneSituation {
  kind: "breakout" | "beginner";
  zones?: FaceZone[];
  usual_spots?: boolean | null;
  symptoms?: string[];
  weeks_ago?: number;
  using?: { product_id: string; started_weeks_ago: number }[];
  answers?: Record<string, string>;
}

// ---------------------------------------------------------------- write-back
export interface WriteBack {
  outcome: ProductOutcome;
  changed: boolean;
  note: string;
  from_verdict: VerdictCode;
  refused_upgrade: boolean;
  rule_version: string;
}

// ---------------------------------------------------------------- start here
export interface BeginnerQuestion {
  id: string;
  text: string;
  why: string;
  choices: { value: string; label: string }[];
}

export interface StarterPlan {
  skin_type: {
    value: string | null;
    /** "answers" until a scan supplies one, which is what the screen says out loud. */
    source: "answers" | "scan";
    label: string;
    zones: Record<string, string>;
    sensitive: boolean;
    line: string;
  };
  concerns: { concern: string; word: string; score: number | null; sentence: string }[];
  steps: { role: string; product: Product; check: CartCheck }[];
  one_at_a_time: string;
  next_step: string;
  rule_version: string;
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
  /** The rebuy decision, mapped strictly from the verdict by the backend (evidence.rebuy_line). */
  rebuy: string;
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
  // How the photo arrived. Display only: the comparability gate never reads it.
  capture_source?: "camera" | "upload" | null;
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
  // Uploaded first photos: "exif" (times within 15 minutes) or "user-confirmed" (no times; the user said yes).
  baseline_timing?: "exif" | "user-confirmed" | null;
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
  /** Live judge scans stop at these YouCam unit totals, then replay prepared data. */
  judge_caps?: { total: number; daily: number; spent: { total: number; today: number } };
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
  record_types?: RecordType[];
  rules?: string[];
  // The new engines' own rules and vocabulary, so no screen hard-codes a list.
  outcomes?: {
    values: OutcomeValue[];
    labels: Record<string, string>;
    too_early: string;
    suited_min_weeks: number;
    zones: FaceZone[];
  };
  cartcheck?: { ladder: CartRung[]; labels: Record<CartRung, string>; unknown_label: string; no_scan_line: string };
  patterns?: { tiers: PatternTier[]; labels: Record<PatternTier, string> };
  triage?: { window_weeks: number[]; long_use_weeks: number; purge_settle_weeks: number };
  engine_rules?: string[];
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

// notice: a plain message when the server replayed prepared data instead of a live scan (unit caps).
export type ScanResult = { capture: Capture; comparability: Comparability | null; notice?: string | null };

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

/** The free checks on uploaded photos (no YouCam call, nothing stored): pass, or one plain fix. */
export interface PrecheckResult {
  ok: boolean;
  code: string | null;
  message: string | null;
  needs_confirmation: boolean;
  timing: "exif" | "user-confirmed" | null;
  photos: {
    index: number;
    ok: boolean;
    code?: string;
    message?: string;
    warning?: string | null;
    hour?: number | null;
    device?: string;
    mode?: string;
  }[];
  comparability: (Comparability | null)[] | null;
}

export type UploadScanResult = { captures: Capture[]; comparability: (Comparability | null)[]; notice?: string | null };

export interface UploadInput {
  files: File[];
  phase: "baseline" | "checkin";
  trialId?: string;
  sameSitting?: boolean | null;
  persona?: string;
  fixtureSet?: string | null;
  place?: Place | null;
}

function uploadForm(u: UploadInput): FormData {
  const f = new FormData();
  u.files.forEach((file, i) => f.append("images", file, file.name || `photo-${i + 1}.jpg`));
  f.append("phase", u.phase);
  f.append("actions", DEFAULT_ACTIONS.join(","));
  if (u.trialId) f.append("trial_id", u.trialId);
  if (u.sameSitting !== null && u.sameSitting !== undefined) f.append("same_sitting", String(u.sameSitting));
  if (u.persona) f.append("persona", u.persona);
  if (u.fixtureSet) f.append("fixture_set", u.fixtureSet);
  if (u.place) f.append("place", u.place);
  return f;
}

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
  // Typed by this person: also kept on this device, offered to their profile after logging in.
  addRecord: async (r: Omit<HistoryRecord, "id">) => {
    const out = await call<HistoryRecord>("/api/history", json("POST", r));
    mirrorRecord({ type: r.type, product_id: r.product_id ?? null, ingredient: r.ingredient ?? null, note: r.note ?? "" });
    return out;
  },
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
  // ---- what happened (app/outcomes.py)
  outcomes: () => call<ProductOutcome[]>("/api/outcomes"),
  addOutcome: (o: OutcomeIn) => call<ProductOutcome>("/api/outcomes", json("POST", o)),
  removeOutcome: (id: string) => call<unknown>(`/api/outcomes/${id}`, { method: "DELETE" }),
  // ---- the patterns your own records make (app/patterns.py). Two separate runs.
  patterns: () => call<Patterns>("/api/patterns"),
  // ---- before you buy (app/cartcheck.py)
  cartCheck: (productId: string, useScan = true) =>
    call<CartCheck>("/api/cartcheck", json("POST", { product_id: productId, use_scan: useScan })),
  store: () => call<Store>("/api/store"),
  // ---- after a breakout (app/triage.py)
  triage: (body: TriageIn) => call<Triage>("/api/triage", json("POST", body)),
  // ---- the loop closing (app/writeback.py). The GET writes nothing.
  writebackPreview: (trialId: string) => call<WriteBack>(`/api/trials/${trialId}/writeback`),
  writeback: (trialId: string) =>
    call<WriteBack>(`/api/trials/${trialId}/writeback`, { method: "POST" }),
  // ---- start here (app/beginner.py)
  beginnerQuestions: () =>
    call<{ questions: BeginnerQuestion[]; rule_version: string }>("/api/beginner/questions"),
  beginnerPlan: (answers: Record<string, string>) =>
    call<StarterPlan>("/api/beginner/plan", json("POST", { answers })),
  demoReset: () => call<unknown>("/api/demo/reset", { method: "POST" }),
  /** Guided demo: write one prepared scene (server demo mode only). */
  demoScene: (name: string) =>
    call<{ scene: string; trial_id: string | null; situation?: SceneSituation | null }>(
      `/api/demo/scene/${name}`,
      { method: "POST" }
    ),
  // ---- the basket (app/basket.py, app/needs.py, app/undertone.py)
  basketQuestions: () => call<BasketQuestions>("/api/basket/questions"),
  chips: () => call<ChipsState>("/api/chips"),
  /** Replaces the whole list; the engine validates each chip and infers nothing. */
  setChips: (chips: ChipIn[]) => call<ChipsState>("/api/chips", json("PUT", { chips })),
  matchChip: (text: string) =>
    call<{ match: ChipSpec | null; line: string }>("/api/chips/match", json("POST", { text })),
  /** A pasted ingredient list, checked like the shop's stock. Never stored. */
  pasteCheck: (text: string, job: PasteJob, nickname?: string) =>
    call<PasteResult>("/api/pastecheck", json("POST", { text, job, nickname: nickname || null })),
  /** The demo persona's prepared face. Never calls YouCam. */
  basket: (answers: Record<string, string>, persona = "riya") =>
    call<Basket>("/api/basket", json("POST", { answers, persona })),
  /** A selfie. Live only with the passcode on a live server; otherwise the prepared face, labelled. */
  basketScan: (image: File | null, answers: Record<string, string>, persona = "riya") => {
    const f = new FormData();
    if (image) f.append("image", image, image.name || "selfie.jpg");
    f.append("answers", JSON.stringify(answers));
    f.append("persona", persona);
    return call<Basket>("/api/basket/scan", { method: "POST", body: f });
  },
  /** Free checks on uploaded photos. Never calls YouCam. */
  precheck:(u: UploadInput) => call<PrecheckResult>("/api/upload/precheck", { method: "POST", body: uploadForm(u) }),
  /** Scan uploaded photos. The server re-runs every precheck itself first. */
  uploadScan: (u: UploadInput) => call<UploadScanResult>("/api/upload/scan", { method: "POST", body: uploadForm(u) }),
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

// 4 SD concerns: the 9-unit price tier. Same as the server default (app/main.py DEFAULT_ACTIONS).
export const DEFAULT_ACTIONS = ["redness", "acne", "texture", "pore"];
export const CONCERNS = DEFAULT_ACTIONS;

// ---------------------------------------------------------------- accounts (/api/me)
// Every call carries the Supabase access token; the server reads the user from it and nothing
// else. Face photos are never stored: a scan is results only.
export interface Profile {
  user_id: string;
  display_name: string;
  finish_goal: "dewy" | "natural" | "matte" | null;
  budget: "under_700" | "under_1000" | "any" | null;
  beginner: boolean;
  created_at: string;
  updated_at: string;
}
export interface MeState {
  profile: Profile;
  first_login: boolean;
  photo_line: string;
}
export interface SavedChip extends ChipIn {
  id: string;
  kind: "chip";
  clinician_confirmed: boolean;
  created_at: string;
}
export interface SavedRecord {
  id: string;
  kind: "record";
  type: RecordType;
  product_id: string | null;
  ingredient: string | null;
  note: string;
  clinician_confirmed: boolean;
  created_at: string;
}
export interface SavedBasket {
  id: string;
  created_at: string;
  demo: boolean;
  basket: Omit<Basket, "id" | "tryon"> & { source?: string };
  start_plan: StartPlan | null;
  engine_versions: Record<string, string>;
}
export interface SavedScan {
  id: string;
  created_at: string;
  zone_types: Record<string, string>;
  concern_values: Record<string, number>;
  undertone: string | null;
  undertone_method: string | null;
  engine_versions: Record<string, string>;
  findings?: ScanFindings | null;
}

/** The saved ids kept for one basket. Clinician-confirmed items are always kept by the server. */
export interface ProfileUse {
  chips: string[];
  records: string[];
  shelf: string[];
}

/** Server asleep or briefly down (a free host's cold start): not the same as being logged out. */
export const isWaking = (e: unknown) => e instanceof ApiError && [0, 502, 503, 504].includes(e.status);
export const isLoggedOut = (e: unknown) => e instanceof ApiError && e.status === 401;

const auth = (token: string, init: RequestInit = {}): RequestInit => ({
  ...init,
  // no-store: user data never goes into any cache (the service worker skips these too).
  cache: "no-store",
  headers: { ...(init.headers as Record<string, string>), Authorization: `Bearer ${token}` },
});

export const meApi = {
  get: (t: string) => call<MeState>("/api/me", auth(t)),
  setProfile: (t: string, p: Pick<Profile, "display_name" | "finish_goal" | "budget" | "beginner">) =>
    call<Profile>("/api/me/profile", auth(t, json("PUT", p))),
  history: (t: string) =>
    call<{ chips: SavedChip[]; records: SavedRecord[]; catalogue: ChipSpec[]; reactions: Record<string, string> }>(
      "/api/me/history",
      auth(t)
    ),
  setChips: (t: string, chips: ChipIn[]) => call<{ chips: SavedChip[] }>("/api/me/chips", auth(t, json("PUT", { chips }))),
  addRecord: (t: string, r: Omit<HistoryRecord, "id"> & { clinician_confirmed?: boolean }) =>
    call<SavedRecord>("/api/me/history", auth(t, json("POST", r))),
  removeRecord: (t: string, id: string) => call<unknown>(`/api/me/history/${id}`, auth(t, { method: "DELETE" })),
  shelf: (t: string) => call<{ product_ids: string[] }>("/api/me/shelf", auth(t)),
  setShelf: (t: string, ids: string[]) =>
    call<{ product_ids: string[] }>("/api/me/shelf", auth(t, json("PUT", { product_ids: ids }))),
  /** A logged-in basket on the prepared face, from the answers and the saved items kept for it. */
  basket: (t: string, b: { answers: Record<string, string>; use: ProfileUse; update_profile: boolean }) =>
    call<Basket>("/api/me/basket", auth(t, json("POST", { ...b, persona: "riya" }))),
  /** A selfie, logged in: the same as api.basketScan, with the user's own history. */
  basketScan: (t: string, image: File, answers: Record<string, string>, use: ProfileUse) => {
    const f = new FormData();
    f.append("image", image, image.name || "selfie.jpg");
    f.append("answers", JSON.stringify(answers));
    f.append("profile", JSON.stringify(use));
    return call<Basket>("/api/basket/scan", auth(t, { method: "POST", body: f }));
  },
  baskets: (t: string) => call<SavedBasket[]>("/api/me/baskets", auth(t)),
  saveBasket: (t: string, basketId: string) =>
    call<SavedBasket>("/api/me/baskets", auth(t, json("POST", { basket_id: basketId }))),
  removeBasket: (t: string, id: string) => call<unknown>(`/api/me/baskets/${id}`, auth(t, { method: "DELETE" })),
  scans: (t: string) => call<{ scans: SavedScan[]; photo_line: string }>("/api/me/scans", auth(t)),
  importDevice: (t: string, d: { chips: unknown[]; records: unknown[]; shelf: string[] }) =>
    call<{ chips: number; records: number; shelf: number }>("/api/me/import", auth(t, json("POST", d))),
  exportData: (t: string) => call<unknown>("/api/me/export", auth(t)),
  deleteAccount: (t: string) => call<{ deleted: boolean }>("/api/me", auth(t, { method: "DELETE" })),
};
