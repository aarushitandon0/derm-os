// Proves the "Add the history saved on this device to your profile?" rule (src/deviceImport.ts):
// device history is sent only on "yes", never automatically, and the question is asked once.
//   node scripts/check-import.mjs     (Node 22.18+ / 23.6+ runs the .ts file directly; run in CI)
import * as M from "../src/deviceImport.ts";

const data = { chips: [{ chip: "vitamin_c", reaction: "itched" }], records: [], shelf: ["p1"] };
let bad = 0;
const check = (name, ok) => {
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}`);
};

let sent = 0;
const send = async () => {
  sent++;
};

check("asks when the device has history", M.shouldAsk(data, false));
check("never asks twice", !M.shouldAsk(data, true));
check("doesn't ask with nothing on the device", !M.shouldAsk(M.EMPTY_DEVICE, false));

check("'no' sends nothing", (await M.answerImport("no", data, send)) === "declined" && sent === 0);
check("an unknown answer sends nothing", (await M.answerImport("maybe", data, send)) === "declined" && sent === 0);
check("'yes' with nothing sends nothing", (await M.answerImport("yes", M.EMPTY_DEVICE, send)) === "nothing" && sent === 0);
check("'yes' sends once", (await M.answerImport("yes", data, send)) === "imported" && sent === 1);

console.log(bad ? `${bad} failure(s)` : "device import: sent only on yes");
process.exit(bad ? 1 : 0);
