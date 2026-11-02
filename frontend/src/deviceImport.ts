// The one question after logging in: "Add the history saved on this device to your profile?"
// Pure on purpose (no storage, no network), so scripts/check-import.mjs can prove the rule:
// nothing is imported unless the answer is "yes". Never automatic.

export interface DeviceChip {
  chip: string;
  reaction: string;
  product_name?: string;
  confirmed_allergy?: boolean;
  usual_spots_settled?: string | null;
  purge_choice?: string | null;
}
export interface DeviceRecord {
  type: "suspected_reaction" | "avoid" | "confirmed_allergy";
  product_id: string | null;
  ingredient: string | null;
  note: string;
}
/** Only what the person tapped or typed on this device, never a demo persona's prepared history. */
export interface DeviceData {
  chips: DeviceChip[];
  records: DeviceRecord[];
  shelf: string[];
}

export const EMPTY_DEVICE: DeviceData = { chips: [], records: [], shelf: [] };

export const IMPORT_QUESTION = "Add the history saved on this device to your profile?";

export const hasDeviceData = (d: DeviceData) => d.chips.length + d.records.length + d.shelf.length > 0;

/** Ask once per account on this device, and only when there is something to add. */
export const shouldAsk = (d: DeviceData, alreadyAsked: boolean) => !alreadyAsked && hasDeviceData(d);

export type ImportAnswer = "yes" | "no";
export type ImportOutcome = "imported" | "declined" | "nothing";

/** The only path that sends device data to the profile. `send` runs on "yes" and nowhere else. */
export async function answerImport(
  answer: ImportAnswer,
  data: DeviceData,
  send: (d: DeviceData) => Promise<unknown>
): Promise<ImportOutcome> {
  if (answer !== "yes") return "declined";
  if (!hasDeviceData(data)) return "nothing";
  await send(data);
  return "imported";
}

export const summary = (d: DeviceData) => {
  const parts = [
    d.chips.length && `${d.chips.length} ingredient${d.chips.length === 1 ? "" : "s"}`,
    d.records.length && `${d.records.length} history note${d.records.length === 1 ? "" : "s"}`,
    d.shelf.length && `${d.shelf.length} product${d.shelf.length === 1 ? "" : "s"} you own`,
  ].filter(Boolean);
  return parts.join(", ");
};
