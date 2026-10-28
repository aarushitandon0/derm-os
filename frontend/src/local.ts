// Per-device conveniences only (onboarding seen, today's ticks, personal notes).
// Storage can be blocked or empty; every access is guarded and the app works without it.
const PREFIX = "dermos.";

export function readLocal<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeLocal(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* storage unavailable: the value just isn't remembered */
  }
}

export const KEYS = {
  onboarded: "onboarded",
  ticks: (day: string) => `ticks.${day}`,
  notes: (trialId: string) => `notes.${trialId}`,
};
