import { EMPTY_DEVICE, type DeviceChip, type DeviceData, type DeviceRecord } from "./deviceImport";
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

// ---- history saved on this device (deviceImport.ts)
// Only what the person tapped or typed here: never a demo persona's prepared history. Offered to
// their profile once, after logging in, and only sent on "yes".

const DEVICE_KEY = "device.history";
export const deviceData = (): DeviceData => ({ ...EMPTY_DEVICE, ...readLocal<Partial<DeviceData>>(DEVICE_KEY, {}) });
const saveDevice = (d: DeviceData) => writeLocal(DEVICE_KEY, d);
export const clearDevice = () => saveDevice(EMPTY_DEVICE);

export function mirrorChip(c: DeviceChip) {
  const d = deviceData();
  saveDevice({ ...d, chips: [...d.chips.filter((x) => x.chip !== c.chip), c] });
}
export function unmirrorChip(id: string) {
  const d = deviceData();
  saveDevice({ ...d, chips: d.chips.filter((x) => x.chip !== id) });
}
export function mirrorRecord(r: DeviceRecord) {
  const d = deviceData();
  saveDevice({ ...d, records: [...d.records, r].slice(-100) });
}
export function mirrorShelf(added: string[], removed: string[]) {
  const d = deviceData();
  const shelf = [...new Set([...d.shelf, ...added])].filter((id) => !removed.includes(id));
  saveDevice({ ...d, shelf });
}
/** Asked once per account on this device. */
export const importAskedKey = (uid: string) => `importAsked.${uid}`;
