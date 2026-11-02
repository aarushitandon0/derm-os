// All user-facing wording that carries a claim lives here, so it can be read
// against the honesty rules in one place:
//   - strongest claim is "changed during this trial", never "caused by"
//   - symptoms outrank scores
//   - unknown is never a pass
//   - decision support, never diagnosis
import type {
  CartRung,
  Capture,
  CheckStatus,
  ConditionField,
  EffectiveOutcome,
  FaceZone,
  PatternTier,
  Place,
  RecordType,
  VerdictCode,
} from "./api";

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
    next: "This moved further than your own scan-to-scan range, on photos taken under matching conditions.",
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
    rule: "Confirmed by a clinician. Blocks the ingredient and is marked as confirmed in your visit brief.",
    target: "ingredient",
  },
};

export const CHECK: Record<CheckStatus, { label: string }> = {
  pass: { label: "No conflict found" },
  blocked: { label: "Blocked" },
  unknown: { label: "Unknown, not a pass" },
  nothing_to_check: { label: "Nothing to check against yet" },
};
export const INCOMPLETE_TAG = "ingredient_list_incomplete";
export const INCOMPLETE_LABEL = "Ingredient list incomplete";

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
  treatment: "Treatment",
  moisturiser: "Moisturise",
  sunscreen: "Protect",
};

export const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

export const fmtDate = (iso: string | Date) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export const addDays = (iso: string, d: number) => new Date(new Date(iso).getTime() + d * 864e5);

export const daysSince = (iso: string) => Math.floor((Date.now() - new Date(iso).getTime()) / 864e5);

export const NOT_DIAGNOSIS = "Decision support, not diagnosis.";

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
  notCompared: "Not compared",
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

// ------------------------------------------------------------------ capture
// The method, said once in the same words on the Learn page and in the README.
export const NORMALISE_LINE =
  "Each photo is cropped and scaled the same way, so your distance from the camera doesn't change the comparison.";

// Optional, asked during the baseline so a check-in can say where it was. Never guessed from pixels.
export const PLACES: { value: Place; label: string; phrase: string | null }[] = [
  { value: "window", label: "By a window", phrase: "by a window" },
  { value: "ceiling", label: "Ceiling light", phrase: "under a ceiling light" },
  { value: "lamp", label: "Lamp", phrase: "under a lamp" },
  { value: "outdoors", label: "Outdoors", phrase: "outdoors" },
  { value: "other", label: "Somewhere else", phrase: null },
];

/** "9 am", "noon", "3 pm". */
export function hourLabel(h: number): string {
  if (h === 0) return "midnight";
  if (h === 12) return "noon";
  return h < 12 ? `${h} am` : `${h - 12} pm`;
}

/**
 * "Your first photos: by a window, around 9 am" from the baseline captures, using only what
 * was recorded (the place the user chose, the capture hour). Null when neither is known.
 */
export function baselineWhere(baseline: Pick<Capture, "place" | "fingerprint">[]): string | null {
  const place = baseline.map((c) => c.place).find(Boolean);
  const phrase = PLACES.find((p) => p.value === place)?.phrase ?? null;
  const hours = baseline.map((c) => c.fingerprint?.captured_hour).filter((h): h is number => typeof h === "number");
  const hour = hours.length ? hours[0] : null;
  const bits = [phrase, hour !== null ? `around ${hourLabel(hour)}` : null].filter(Boolean);
  return bits.length ? `Your first photos: ${bits.join(", ")}` : null;
}

export const CAPTURE = {
  baselineLede: "We'll take 3 photos on our own. Look away and back between them.",
  checkinLede: "Two photos in the same spot and light as your baseline.",
  sameSpot: "The same spot and time of day work best.",
  lookAway: (n: number, total: number) => `Photo ${n} of ${total} saved. Look away for a moment, then back at the camera.`,
  holdStill: "Hold still: taking the photo.",
  auto: "The photo takes itself when the checks hold steady. Or tap.",
  waiting: "The shutter waits for the checks above.",
  placeQuestion: "Where are you taking these? (optional)",
  placeWhy: "So your check-ins can remind you.",
  cameraTooSmall:
    "This camera's picture is too small for a scan, even up close. Open derm//os on your phone instead.",
};

// Upload photos instead of taking them (components/UploadPhotos.tsx).
export const UPLOAD = {
  instead: "Upload photos instead",
  insteadWhy: "Choose photos from your gallery. They get the same checks as the camera.",
  lede: {
    baseline: "Choose 3 photos of your face, taken a few minutes apart in one sitting, in the same spot and light.",
    checkin: "Choose 2 photos, taken in the same spot and light as your first photos.",
  } as Record<"baseline" | "checkin", string>,
  choose: (n: number) => `Choose ${n} photos`,
  chooseAgain: "Choose different photos",
  unedited: "Use unedited photos: no filters or beauty mode.",
  demo: "Demo mode: the checks run on your real photos; the scores are prepared data. Nothing is sent to YouCam.",
  wrongCount: (need: number, got: number) => `You chose ${got}. Choose exactly ${need} photos.`,
  checking: (n: number) => `Checking ${n} photos on our server. Nothing is sent to YouCam for this.`,
  checkFailed: "The photos couldn't be checked. Try again.",
  scanFailed: "The scan didn't go through. Try again.",
  photoLine: (hour: number | null, device: string) =>
    `${hour === null ? "time not recorded" : `taken around ${String(hour).padStart(2, "0")}:00`} · ${
      device === "not recorded" ? "camera not recorded" : device
    }`,
  photoBad: "needs a different photo",
  whyAsk: "These photos don't say when they were taken. Your first photos set your normal range, so they need to come from one sitting.",
  passed: "These photos passed every check. Nothing has been sent to YouCam yet.",
  scan: (n: number) => `Scan these ${n} photos`,
  scanning: "Scanning…",
  saved: (n: number, phase: "baseline" | "checkin") =>
    phase === "baseline" ? `${n} photos saved. These set your normal range.` : `${n} photos saved and compared with your first photos.`,
  userConfirmed: "You confirmed these were taken in one sitting; that's noted with them.",
};

// ------------------------------------------------------------------ the three moments
// docs/STRATEGY.md section 4. Home asks one question and offers the three moments people
// actually have, plus a way in for someone who has never used anything.
export const HOME_QUESTION = "What's going on with your skin today?";
export const HOME_VALUE_LINE =
  "derm//os checks products against your own skin and your own history.";

export type MomentId = "buy" | "breakout" | "mirror" | "start";

export const MOMENTS: { id: MomentId; label: string; sub: string; to: string }[] = [
  {
    id: "buy",
    label: "I'm about to buy something",
    sub: "Check it against your skin, your history and your shelf before you spend.",
    to: "/store",
  },
  {
    id: "breakout",
    label: "My skin just broke out",
    sub: "Work out what changed 2–8 weeks ago, and whether it could be purging.",
    to: "/breakout",
  },
  {
    id: "mirror",
    label: "Is my product working?",
    sub: "One new photo compared with your first scan, in plain words.",
    to: "/progress",
  },
];

export const START_HERE = {
  label: "New to skincare? Start here",
  sub: "Four questions, a scan, and a 3-step starter checked against your answers.",
  to: "/start-here",
};

// ------------------------------------------------------------------ outcomes
export const OUTCOME: Record<EffectiveOutcome, { label: string; chip: string; tone: Tone }> = {
  suited: { label: "Suited me", chip: "Suited", tone: "moved" },
  irritation: { label: "Itched, stung or burned", chip: "Irritation", tone: "stop" },
  breakout: { label: "Broke me out", chip: "Breakout", tone: "stop" },
  not_sure: { label: "Not sure", chip: "Not sure", tone: "unsure" },
  too_early: { label: "Too early to say", chip: "Too early", tone: "unsure" },
};

export const OUTCOME_HELP: Record<string, string> = {
  suited: "You used it and your skin was fine. It only counts as evidence after 4 weeks.",
  irritation: "It itched, stung, burned or turned you red.",
  breakout: "It gave you spots or closed comedones.",
  not_sure: "You used it and genuinely can't say either way.",
};

export const OUTCOMES_LEDE =
  "What happened, product by product. This is the memory every other screen reads.";
export const SUITED_RULE =
  "“Suited” only counts after 4 weeks of use. Under that it reads “too early to say” and clears nothing.";
export const LEAVE_ON_LABEL = { true: "Stays on", false: "Washed off" };

export const ZONE_LABEL: Record<FaceZone, string> = {
  forehead: "Forehead",
  nose: "Nose",
  cheeks: "Cheeks",
  chin: "Chin",
  jaw: "Jaw",
};

// ------------------------------------------------------------------ patterns
export const TIER: Record<PatternTier, { label: string; tone: Tone; help: string }> = {
  suspect: {
    label: "Suspect",
    tone: "stop",
    help: "In at least 2 products that gave you this problem, and none that suited you.",
  },
  lead: {
    label: "Lead",
    tone: "unsure",
    help: "In 1 product that gave you this problem, and none that suited you. Not enough to call it.",
  },
  cleared_so_far: {
    label: "Used without this problem",
    tone: "steady",
    help: "It is also in something that suited you, so your own history doesn't point at it.",
  },
};

export const PATTERN_KIND: Record<"irritation" | "breakout", { label: string; sub: string }> = {
  irritation: { label: "Itching, stinging, burning", sub: "Kept apart from breakouts on purpose." },
  breakout: { label: "Spots and closed comedones", sub: "Kept apart from irritation on purpose." },
};

export const PERSONAL_LABEL = "From your own records";
export const GENERAL_LABEL = "General knowledge, not about you";
export const EXACT_VS_FAMILY = {
  exact: "The same ingredient, by name",
  family: "A family match, which ranks below an exact one",
};

// ------------------------------------------------------------------ cart check
export const CART_RUNG: Record<CartRung, { tone: Tone; kicker: string }> = {
  blocked: { tone: "stop", kicker: "Blocked" },
  repeats_a_pattern: { tone: "stop", kicker: "Repeats a pattern" },
  patch_test_first: { tone: "unsure", kicker: "Patch-test first" },
  no_conflicts: { tone: "steady", kicker: "No conflicts with your history" },
};

export const CART_LEDE =
  "One product, checked against three things that are all yours. Never a recommendation.";
export const NEXT_STEP_LABEL = "Your next step";
export const CHANGE_NOTHING_LABEL = "Or change nothing";
export const SOURCE_HELP: Record<string, string> = {
  history: "What your own recorded reactions say about this label.",
  skin: "What YouCam measured, against what this product says it is for.",
  shelf: "What it would duplicate or replace, and what it would cost you.",
};

// ------------------------------------------------------------------ store
export const STORE_HELP =
  "A fictional shop, invented for this demo. Tap “Check against my skin” on anything.";
export const CHECK_AGAINST = "Check against my skin";

// ------------------------------------------------------------------ breakout triage
export const BREAKOUT = {
  title: "What changed?",
  lede: "Breakouts from a product usually show up 2–8 weeks later, so we rank by when things started.",
  whenQ: "When did it start?",
  whereQ: "Where is it?",
  usualQ: "Are those your usual spots?",
  usualWhy: "Purging shows up where you normally break out. Spots in a new area point elsewhere.",
  symptomQ: "Any itching, burning or swelling?",
  symptomWhy: "A reaction you can feel outranks everything below.",
  rankingLabel: "What changed, most likely first",
  windowLabel: "In the 2–8 week window",
  purgeLabel: "Could it be purging?",
  zonesLabel: "Where the spots are",
  usualYes: "Yes, my usual spots",
  usualNo: "No, this is a new area",
  usualUnsure: "I'm not sure",
};

export const TRIAGE_TIER_TONE: Record<number, Tone> = {
  0: "stop",
  1: "unsure",
  2: "unsure",
  3: "unsure",
  4: "steady",
  5: "steady",
};

// ------------------------------------------------------------------ the evidence view
/** The grey line above the derm//os verdict, computed from the raw score difference alone. */
export function typicalAppLine(concern: string, deltaMid: number | null): string | null {
  if (deltaMid === null || !Number.isFinite(deltaMid)) return null;
  const points = Math.round(Math.abs(deltaMid));
  if (points < 1) return null;
  const verb = deltaMid > 0 ? "improved" : "got worse by";
  return `A typical app would say: ${concernLabel(concern)} ${verb} ${points} point${points === 1 ? "" : "s"}!`;
}
export const TYPICAL_APP_LABEL = "What most apps would tell you";
export const DERMOS_SAYS_LABEL = "What derm//os says";

// ------------------------------------------------------------------ write-back
export const WRITEBACK = {
  label: "Remember this result",
  lede: "The verdict goes into this product's record, so your next purchase check knows it.",
  done: "Written into your history.",
  refused: "Recorded as “not sure”. A result that can't tell either way is never filed as suiting you.",
  button: "Write this into my history",
};

// ------------------------------------------------------------------ start here
export const BEGINNER = {
  title: "Start here",
  lede: "Four questions, then your skin type and top concerns in plain words.",
  typeLabel: "Your skin type",
  concernsLabel: "What YouCam measured",
  starterLabel: "A 3-step starter, checked against your answers",
  oneAtATimeLabel: "How to start it",
  noScanYet:
    "No scan yet, so your skin type here comes from your answers. A scan can read it directly.",
};

export const DEMO_DATA_TAG = "Demo data";
