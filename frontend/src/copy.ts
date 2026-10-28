// All user-facing wording that carries a claim lives here, so it can be read
// against the honesty rules in one place:
//   - strongest claim is "changed during this trial", never "caused by"
//   - symptoms outrank scores
//   - unknown is never a pass
//   - decision support, never diagnosis
import type { CheckStatus, ConditionField, RecordType, VerdictCode } from "./api";

export type Tone = "stop" | "unsure" | "steady" | "moved";

export const VERDICT: Record<VerdictCode, { kicker: string; tone: Tone; next: string }> = {
  stop_reaction: {
    kicker: "Stop",
    tone: "stop",
    next: "A reaction you can feel outranks any score. If it's severe or getting worse, see a clinician; your visit brief is ready to take along.",
  },
  cant_tell_no_baseline: {
    kicker: "Can't tell yet",
    tone: "unsure",
    next: "Finish the scans first: 3 for the baseline and 2 at each check-in.",
  },
  cant_tell_not_comparable: {
    kicker: "Can't tell",
    tone: "unsure",
    next: "Retake the check-in under your baseline conditions. The fixes are listed below.",
  },
  cant_tell_several_changes: {
    kicker: "Can't tell which",
    tone: "unsure",
    next: "With more than one new leave-on product, no single one can be credited or blamed. Keep one, pause the other, and restart.",
  },
  no_detectable_change: {
    kicker: "No detectable change yet",
    tone: "steady",
    next: "Your new scores fall inside the range your face moves on its own. Keep going to the next check-in.",
  },
  moved_beyond_noise: {
    kicker: "Changed during this trial",
    tone: "moved",
    next: "This moved further than your own scan-to-scan range. Seasons, sleep and cycles move skin too, so this is not proof the product did it.",
  },
};

export const RECORD: Record<RecordType, { label: string; short: string; rule: string; target: "product" | "ingredient" }> = {
  suspected_reaction: {
    label: "This product bothered me",
    short: "Reaction",
    rule: "Blocks that one product. It doesn't turn any ingredient into an allergy.",
    target: "product",
  },
  avoid: {
    label: "I avoid this ingredient",
    short: "Avoid",
    rule: "Your choice. Blocks any product whose label lists it, including its synonyms.",
    target: "ingredient",
  },
  confirmed_allergy: {
    label: "Clinician-confirmed allergy",
    short: "Confirmed",
    rule: "Diagnosed by a clinician. Blocks the ingredient and is marked as confirmed in your visit brief.",
    target: "ingredient",
  },
};

export const CHECK: Record<CheckStatus, { label: string }> = {
  pass: { label: "No conflict found" },
  blocked: { label: "Blocked" },
  unknown: { label: "Unknown, not a pass" },
};

export const CONCERN_LABEL: Record<string, string> = {
  redness: "Redness",
  texture: "Texture",
  acne: "Breakouts",
  pore: "Pores",
  oiliness: "Oiliness",
  moisture: "Moisture",
  radiance: "Radiance",
  age_spot: "Spots",
};

export const concernLabel = (c: string) => CONCERN_LABEL[c] ?? c.replace(/_/g, " ");

export const SYMPTOM_LABEL: Record<string, string> = {
  burning: "Burning",
  stinging: "Stinging",
  swelling: "Swelling",
  itching: "Itching",
  hives: "Hives",
  blistering: "Blistering",
  rash: "Rash",
  peeling_painful: "Painful peeling",
  oozing: "Oozing",
  dryness: "Dryness",
  tightness: "Tightness",
  new_breakouts: "New breakouts",
};
export const MILD_SYMPTOMS = ["dryness", "tightness", "new_breakouts"];
export const symptomLabel = (s: string) => SYMPTOM_LABEL[s] ?? s.replace(/_/g, " ");

export const ROLE_LABEL: Record<string, string> = {
  cleanser: "Cleanse",
  toner: "Tone",
  serum: "Serum",
  treatment: "Treat",
  moisturiser: "Moisturise",
  sunscreen: "Protect",
};

export const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

export const fmtDate = (iso: string | Date) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export const addDays = (iso: string, d: number) => new Date(new Date(iso).getTime() + d * 864e5);

export const daysSince = (iso: string) => Math.floor((Date.now() - new Date(iso).getTime()) / 864e5);

export const NOT_DIAGNOSIS = "Decision support, not a diagnosis.";

// ------------------------------------------------------------------ redesign copy
// Reactions: a stop symptom stays in force until the user marks it resolved.
export const REACTION_RULE =
  "A reported reaction stays in force for the rest of the trial, even if later check-ins are clear, until you mark it resolved.";

// Capture-quality rows. The state of each row comes from the backend's comparability result.
export const CONDITION: Record<ConditionField, { label: string }> = {
  lighting: { label: "Lighting" },
  face_size: { label: "Face size" },
  head_pose: { label: "Head pose" },
  time_of_day: { label: "Time of day" },
  device: { label: "Device" },
  mode: { label: "Scan mode" },
};
export const CONDITION_ROWS: ConditionField[] = ["lighting", "face_size", "head_pose", "time_of_day", "device"];
export const CONDITION_STATE = {
  match: "Matches your baseline",
  liveCheck: "Passed the live check",
  recorded: "Recorded for your baseline",
  notRecorded: "Not recorded for this photo, so not compared",
};

// The analysing steps follow the real request: upload, wait for analysis, response, refresh.
export const ANALYSIS_STEPS = {
  upload: "Sending your photo",
  analyse: "Analysing concerns",
  calibrate: { baseline: "Adding to your baseline", checkin: "Comparing with your baseline" },
  prepare: "Preparing your results",
};

export const PRIVACY = {
  live: "Your photo is sent to YouCam for analysis. As soon as the results and marked areas are saved here, derm//os asks YouCam to delete that scan, including your photo. This server keeps the scores, the capture conditions and the marked areas, never the photo. You can delete them anytime.",
  demo: "Demo mode: your photo isn't sent to YouCam. It's measured for light and framing, then discarded. You can delete saved scans anytime.",
};

// What "Delete my saved scans" removes, and where. Shown before the user confirms.
export const DELETE_SCANS = {
  confirm: [
    "Delete every saved scan?",
    "",
    "On this derm//os server: each scan's scores, its capture conditions (light, framing, head angle, time, camera label) and any saved YouCam mask images.",
    "At YouCam: derm//os already asked YouCam to delete each live scan right after it finished. Any scan YouCam hasn't confirmed deleted is asked again now; that removes your uploaded photo and its results there.",
    "",
    "Your trials, symptom log, history and shelf stay. Your photo was never stored on this server.",
  ].join("\n"),
  short:
    "Removes from this server: scores, capture conditions and saved mask images for every scan. At YouCam: asks again to delete any live scan not yet confirmed deleted (your photo and its results). Trials, history and shelf stay.",
};

/** One sentence on what happened, from the server's counts. */
export function deletedSummary(r: {
  deleted: number;
  youcam?: { already_deleted: number; requested: number; deleted: number; failed: number; skipped_reason: string | null };
}): string {
  if (!r.deleted) return "There were no saved scans.";
  const parts = [`Deleted ${r.deleted} saved scan${r.deleted === 1 ? "" : "s"} from this server.`];
  const y = r.youcam;
  if (y) {
    if (y.already_deleted) parts.push(`YouCam had already confirmed deleting ${y.already_deleted}.`);
    if (y.requested && y.skipped_reason === "no_key")
      parts.push(`${y.requested} couldn't be sent to YouCam (no API key on this server); YouCam keeps task data on its own schedule.`);
    else {
      if (y.deleted) parts.push(`YouCam confirmed deleting ${y.deleted} more.`);
      if (y.failed) parts.push(`${y.failed} YouCam delete request${y.failed === 1 ? "" : "s"} didn't go through.`);
    }
  }
  return parts.join(" ");
}

export const MASKS_DEMO = "Mask images aren't included in the public demo.";

export const NOISE_CAPTION =
  "Small ups and downs are normal. We only count a change if it's bigger than your personal noise floor.";

export const fmtLong = (iso: string | Date) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

export const fmtTime = (iso: string | Date) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/** Today's date in the user's own time zone, as YYYY-MM-DD. */
export const localISODate = (d: Date = new Date()) => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};
